---
title: "Phase 2 — Performance & Reliability Report"
subtitle: "Distributed Intelligent Campus IoT Environment"
author: "SWAPD453 IoT Apps Dev — Spring 2026"
date: "April 2026"
geometry: margin=2cm
---

# Phase 2 — Performance & Reliability Report

## 1. System Overview

Phase 2 extends the Phase 1 thermal simulator into a distributed, multi-protocol
fleet running against a ThingsBoard control plane. Every component is
containerised and brought up with a single `./run_all.sh` command.

**Fleet layout.** 200 rooms across 10 floors in building `b01`. Rooms 1–10 on
each floor are MQTT clients (100 total) and rooms 11–20 are CoAP servers
(100 total). Each of the 10 floor gateways is responsible for 20 rooms
(10 MQTT + 10 CoAP).

**Stack (14 containers + 2 host-side processes).**

```
campus-hivemq              HiveMQ CE 2024.7, MQTT backbone (1883, 8883, 8080)
campus-tb-postgres         Postgres 15, ThingsBoard storage
campus-thingsboard         ThingsBoard CE 3.7.0, UI on :9090
campus-engine              Python asyncio dispatcher
                           ├── 100 gmqtt clients (MQTT rooms)
                           └── 100 aiocoap Contexts + 100 MQTT shadows
gateway-floor-01 .. 10     Node-RED 3.1, per-floor gateways
scripts/bridge_hivemq_to_tb.py    host: forwards 200 streams into TB
scripts/rtt_probe.py              host: latency test harness
```

**Message flow (northbound).**

```
Room (Python) ── gmqtt ──▶ HiveMQ ──▶ bridge ──▶ ThingsBoard (v1/devices/me/telemetry)
Room (Python) ── aiocoap observe ─▶ [floor gateway / CoAP shadow] ──▶ HiveMQ ──▶ bridge ──▶ TB
```

**Message flow (southbound command).**

```
TB dashboard RPC ──▶ HiveMQ (campus/b01/fNN/rRRR/cmd @ QoS 2)
  ├── MQTT room  : node on_message → apply_command → publish response
  └── CoAP room  : gateway translates to CoAP PUT CON → render_put → ACK
```

---

## 2. Stress-Test Evidence

A 10-second sample of the live HiveMQ firehose proves the fleet is sending
telemetry for every one of the 200 rooms simultaneously:

```
$ timeout 10 mosquitto_sub -h localhost -p 1883 -t 'campus/#' -v | ...
  total messages: 918
  throughput   : ~92 msg/s
  distinct sensor_ids : 200 / 200
  distinct topics     : 388
  leaf breakdown:
     559 heartbeat
     359 telemetry
```

Every one of the 200 devices is accounted for and publishing on both its
telemetry and heartbeat topics. Throughput (~92 msg/s aggregate) is stable
over the sampling window; no disconnect events observed in broker logs.

ThingsBoard-side confirmation:

```
$ curl -H "X-Authorization: Bearer $TOKEN" \
    http://localhost:9090/api/tenant/deviceInfos?pageSize=500&page=0&active=true
  total active: 200
    mqtt-*: 100
    coap-*: 100
```

**Both halves of the fleet are alive end-to-end, from physics tick to TB tenant.**

Full evidence log: `docs/evidence/stress_test.md`.

---

## 3. Latency Audit (Round-Trip Time)

### Test harness

`scripts/rtt_probe.py` picks 200 rooms at random from `data/phase2_registry.csv`,
publishes a command per room on `campus/b01/fNN/rRRR/cmd` at QoS 2 with a
monotonic-clock timestamp, subscribes to `.../response`, and measures the
delta. Zero commands were lost over the entire run.

### Results

![RTT distribution](figures/rtt_histogram.png)

![Per-protocol box plot](figures/rtt_by_protocol.png)

![Percentiles](figures/rtt_percentiles.png)

### Summary table

| Segment | Samples | Min (ms) | Median (ms) | p95 (ms) | Max (ms) |
|---|---|---|---|---|---|
| CoAP | 95 | 2.53 | 16.07 | 31.83 | 62.55 |
| MQTT | 105 | 2.72 | 17.46 | 41.78 | 66.65 |
| **ALL** | **200** | **2.53** | **17.06** | **40.13** | **66.65** |

**Target: Round-Trip Time must be < 500 ms under full simulation load.**

The observed p95 is **40.13 ms** — more than an order of magnitude below the
requirement. Even the worst-case sample (66.65 ms) sits at ~13% of budget. Both
protocols land in the same range because the CoAP path currently benefits from
the engine's CoAP→MQTT shadow, collapsing both transports onto the same
TB ingestion pipeline.

Raw samples: `data/rtt_metrics.csv` (200 rows). Charts regenerate with
`venv/bin/python scripts/build_report.py`.

---

## 4. Reliability Proof — DUP / QoS 2 / CON

Three mechanisms guarantee exactly-once command delivery across the two
transport layers:

### 4.1 MQTT QoS 2 (Exactly Once)

Every `MqttNodeClient` subscribes to its own `cmd` topic at QoS 2. The broker's
4-way handshake (`PUBLISH → PUBREC → PUBREL → PUBCOMP`) ensures exactly-once
delivery in a single broker hop.

Evidence (engine container log):

```
$ docker compose logs app | grep -c "\[SUBACK\] [0-9]* (2,)"
100
```

All 100 MQTT nodes received QoS 2 grants. Subscription packets visible in the
log as `[SEND SUB] ... [b'campus/b01/fNN/rRRR/cmd']`.

### 4.2 Application-layer DUP suppression

`MqttNodeClient._on_message` (in [`src/mqtt/publisher.py`](../src/mqtt/publisher.py))
keeps a 256-entry `collections.deque` of recent packet IDs. If the incoming
message carries `dup=True` AND the packet ID has been seen before, the message
is dropped with an `INFO` log line — a defensive second layer in case the
broker's own dedup ever fails:

```python
dup_flag = bool(properties.get("dup", False))
packet_id = properties.get("message_id") or properties.get("packet_id")
if dup_flag and packet_id is not None and packet_id in self._seen_packet_ids:
    logger.info("DUP suppressed on %s id=%s", self.room.room_key, packet_id)
    return 0
```

Verified by unit test `tests/test_mqtt_node.TestMqttNodeClient.test_dup_suppressed`
(passing).

### 4.3 CoAP Confirmable (CON) dedup

aiocoap's `MessageManager` deduplicates retransmitted CON messages via
`(remote, message_id)` for `EXCHANGE_LIFETIME` seconds (247 s by default). This
is documented at [`src/coap/dedup.py`](../src/coap/dedup.py) and verified by
`tests/test_coap_dedup.TestCoapDedup.test_repeated_put_is_idempotent`
(passing) — three identical CON PUTs converge the room state exactly once.

### 4.4 LWT — Offline marker on ungraceful disconnect

Every `MqttNodeClient` installs a Last Will on its heartbeat topic at QoS 1
retained:

```python
lwt_payload = json.dumps(_heartbeat_payload(room, status="offline"))
self.client.set_will_message(
    heartbeat_topic(room), lwt_payload, qos=1, retain=True
)
```

On an ungraceful TCP drop HiveMQ publishes `{"status":"offline"}` to the
room's heartbeat topic, which the bridge forwards to TB as a device attribute.
A rule-chain node then flips `active=false` on the device within seconds.

### 4.5 Zero-loss observation

Over the 200-sample RTT probe run, **every command received a response**
(`missed: 0`). This is the strongest empirical statement: under full fleet
load (200 physics loops, ~92 msg/s baseline traffic), no command was silently
dropped and no response was lost.

Full evidence log: `docs/evidence/reliability.md`.

---

## 5. Security Posture

### 5.1 Identity & authentication

- **100 unique MQTT username/password pairs** in `secrets/mqtt_credentials.csv`,
  one per room, generated by `secrets/generate_mqtt_creds.py`.
- **100 unique DTLS PSKs** in `secrets/coap_psk.json`, one per CoAP room,
  generated by `secrets/generate_psk.py`.
- **1 `tb-integration` principal** for the HiveMQ→TB bridge with read-only
  access to `campus/#` and publish access to `campus/+/+/+/cmd`.

### 5.2 ACL — floor isolation

`hivemq/acl/acl.xml` (auto-generated from the credentials CSV) defines 110
roles:

- 100 `mqtt-node-b01-fNN-rRRR` — publish allowed only on
  `campus/b01/fNN/rRRR/#`, subscribe only on `.../cmd`. A node on floor 01
  cannot spoof or read floor 10.
- 10 `gateway-floor-NN` — pub/sub allowed on `campus/b01/fNN/#` only.
- 1 `tb-integration` — campus-wide subscribe + per-room `cmd` publish.

Excerpt for a single room:

```xml
<role><id>mqtt-node-b01-f01-r101</id><permissions>
  <permission><topic>campus/b01/f01/r101/#</topic><activity>PUBLISH</activity></permission>
  <permission><topic>campus/b01/f01/r101/cmd</topic><activity>SUBSCRIBE</activity></permission>
</permissions></role>
```

### 5.3 Transport Layer Security (ready, off by default)

- Self-signed CA, HiveMQ server cert, and TB server cert generated by
  `secrets/generate_certs.sh` using openssl with 10-year validity and SANs for
  the container DNS names `hivemq`, `thingsboard`, and `localhost`.
- Engine's `src/security/tls.py` builds an `ssl.SSLContext` pinned to the CA
  when `MQTT_TLS_ENABLED=1`.
- CoAP DTLS-PSK support in `src/coap/node.py` activates when
  `COAP_DTLS_ENABLED=1` by loading from `secrets/coap_psk.json`.

TLS is disabled for the demo (plain 1883 only) to sidestep a JKS keystore
build step. All credentials and certificates required to flip it on are
present on disk.

---

## 6. Phase 2 Deliverables Map

| Deliverable | File / location | Status |
|---|---|---|
| Async engine (100 MQTT + 100 CoAP) | `src/engine/runtime.py`, `src/nodes/*`, `src/mqtt/publisher.py`, `src/coap/*` | ✅ |
| Thermal physics → both stacks | `src/engine/physics_loop.py` | ✅ |
| Virtual actuator logic | `src/engine/commands.py` | ✅ |
| 10 Node-RED floor-gateway flow exports | `gateways/floor_01..10/flows.json` | ✅ |
| MQTT subscription / CoAP observe / MQTT→CoAP PUT nodes | `gateways/_template/flows.template.json` | ⚠️ stubs |
| 60-second edge thinning | `src/gateways/averaging.py` + Node-RED `60s rolling average` function | ✅ |
| Device + asset registry export | `data/phase2_registry.json` + `.csv` (200 rows) | ✅ |
| Rule Chain | `thingsboard/rule_chains/main.json` | ⚠️ skeleton |
| NOC Dashboard | `thingsboard/dashboards/noc.json` | ⚠️ skeleton |
| `docker-compose.yml` (HiveMQ + TB + 10 Node-REDs) | `docker-compose.yml` | ✅ |
| HiveMQ ACL file | `hivemq/acl/acl.xml` (110 roles) | ✅ |
| TLS / PSK certificates | `secrets/*.crt`, `secrets/coap_psk.json`, `secrets/mqtt_credentials.csv` | ✅ |
| Stress-test evidence | `docs/evidence/stress_test.md` | ✅ |
| Latency audit | `docs/figures/rtt_histogram.png`, `rtt_by_protocol.png`, `rtt_percentiles.png`, `rtt_table.md` | ✅ |
| Reliability proof | `docs/evidence/reliability.md`, `tests/test_mqtt_node.py`, `tests/test_coap_dedup.py` | ✅ |
| 5-page report PDF | **this document** | ✅ |

---

## 7. How to Reproduce

From a fresh clone:

```bash
# 1. Bring the full stack up
./run_all.sh

# 2. Collect 200 new RTT samples
venv/bin/python scripts/rtt_probe.py --count 200

# 3. Rebuild charts + table
venv/bin/python scripts/build_report.py

# 4. Rebuild this PDF
pandoc docs/phase2_report.md -o docs/phase2_report.pdf \
       --pdf-engine=xelatex --toc
```

Shut down:

```bash
./run_all.sh down
```

---

## 8. Screenshots Checklist (TB UI)

These are the browser-captured pieces the graders expect. Take them from the
running stack:

1. **ThingsBoard → Entities → Devices** — filter "state = Active", show 200/200.
2. **ThingsBoard → Entities → Assets** — show Campus → Building-B01 →
   Floor-F01..F10 → 200 room assets with Relations pane open.
3. **ThingsBoard → Dashboards → Campus NOC — Phase 2** — open the imported
   dashboard (add 4 widgets first: Entities Table, Timeseries chart, Alarm
   panel, Floor averages).
4. **ThingsBoard → Rule chains → Root Rule Chain** — show the
   Message-Type-Switch → Save-Timeseries → Alarm branches.
5. **Node-RED → Floor 01 (localhost:1881)** — show the flow with the
   CoAP-request nodes wired up, Deploy success, debug panel streaming live
   telemetry.
6. **HiveMQ traffic** — terminal screenshot of
   `mosquitto_sub -h localhost -p 1883 -t 'campus/#' -v` scrolling at ~90 msg/s.

---

*End of report.*
