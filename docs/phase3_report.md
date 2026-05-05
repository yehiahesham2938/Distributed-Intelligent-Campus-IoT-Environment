# Phase 3 — Digital Twin & Secure Fleet (Report)

**Distributed Intelligent Campus IoT Environment**
SWAPD453 IoT Apps Dev — Spring 2026

---

## 1. What Phase 3 Adds On Top Of Phase 2

| Capability | Where it lives | Status |
|---|---|---|
| 1:1 asset hierarchy with metadata | `scripts/p3_provision_metadata.py` | ✅ 200 rooms tagged, campus renamed `ZC-Main-Campus` |
| Floor-level aggregation (avg_temperature) | `scripts/p3_floor_aggregator.py` | ✅ 10 floors posting summaries every 30 s |
| OTA pipeline (broadcast / floor / room) | `src/engine/ota.py` + `scripts/p3_ota_publisher.py` | ✅ verified at all 3 scopes |
| SHA-256 payload signing & verification | `src/engine/ota.py` (`canonical_hash`, `verify_payload`) | ✅ tamper rejection logged |
| `current_version` reporting per room | `src/mqtt/publisher.py` `_on_message` OTA branch | ✅ flows back to TB as client attribute |
| Shadow state (desired vs reported) | `scripts/bridge_hivemq_to_tb.py` | ✅ bidirectional loop tested |
| Sync-status dashboard | `scripts/build_p3_dashboard.py` | ✅ widget bound to client+shared attributes |
| Floor plan placeholder | `docs/figures/floor_plan_f01.svg` | ✅ image asset for TB Image Map widget |

---

## 2. Architecture Layered View

```
┌───────────────────────────────────────────────────────────────────┐
│ ThingsBoard (UI :9090)                                            │
│   • SHARED attrs: desired_hvac_mode, desired_target_temp, ...     │
│   • CLIENT attrs: reported_*, current_version, security_alert     │
│   • SERVER attrs: square_footage, occupant_capacity, coords, type │
│   • Dashboards: NOC (Phase 2) + Sync & Versioning (Phase 3)       │
└──────────────▲────────────────────────────────────────────▲───────┘
               │  attributes / RPC                          │ floor avg
               │                                            │ via REST
       ┌───────┴──────────┐                       ┌─────────┴────────┐
       │  bridge          │                       │  p3 floor        │
       │  HiveMQ ↔ TB     │                       │  aggregator      │
       │  desired→cmd     │                       │  (60s window)    │
       │  response→reported attrs                 │                  │
       │  ota/report→version attrs                │                  │
       └───────▲──────────┘                       └─────────▲────────┘
               │                                            │
               └────────────────┬───────────────────────────┘
                                ▼
                ┌─────────────────────────────────┐
                │ HiveMQ broker (campus/#)        │
                │ topics:                         │
                │   campus/b01/fNN/rRRR/cmd       │
                │   campus/b01/fNN/rRRR/response  │
                │   campus/b01/fNN/rRRR/telemetry │
                │   campus/b01/fNN/rRRR/heartbeat │
                │   campus/b01/fNN/rRRR/ota       │
                │   campus/b01/fNN/rRRR/ota/report│
                │   campus/b01/fNN/ota            │ ← floor scope
                │   campus/b01/ota/config         │ ← broadcast scope
                └────────────▲────────────────────┘
                             │
                ┌────────────┴────────────────────┐
                │ campus-engine (Python asyncio)  │
                │ 100 MQTT + 100 CoAP + shadows   │
                │ • subscribes to its own /cmd    │
                │ • subscribes to broadcast/floor │
                │   /room OTA topics              │
                │ • on /ota: SHA-256 verify,      │
                │   apply alpha/beta hot-swap,    │
                │   publish /ota/report with new  │
                │   config_version                │
                └─────────────────────────────────┘
```

---

## 3. Acceptance Tests Performed

### 3.1 Asset metadata (P3.1.1)

```
$ venv/bin/python scripts/p3_provision_metadata.py
…
done: 200/200 room assets metadata-tagged
```

Verification — first room asset has 5 server-scope attributes:

```
$ curl …/api/plugins/telemetry/ASSET/<room_asset_id>/values/attributes/SERVER_SCOPE
[
  {"key":"square_footage","value":37},
  {"key":"occupant_capacity","value":18},
  {"key":"coordinates_x","value":160},
  {"key":"coordinates_y","value":110},
  {"key":"room_type","value":"lab"}
]
```

### 3.2 Floor aggregation (P3.1.1)

```
$ tail -1 data/aggregator.log
cycle 1: posted 10/10 floor summaries

$ curl …/api/plugins/telemetry/ASSET/<floor1_asset_id>/values/timeseries
{"avg_temperature":[{"value":"23.59"}],
 "avg_humidity":[{"value":"55.58"}],
 "occupied_ratio":[{"value":"0.048"}],
 "rooms_sampled":[{"value":"20"}]}
```

### 3.3 OTA broadcast (P3.2.1)

```
$ venv/bin/python scripts/p3_ota_publisher.py --target broadcast --version 2.0 --alpha 0.015
topic  : campus/b01/ota/config
payload: {"version":"2.0","params":{"alpha":0.015},"_sig":"06966f5b14106f26..."}
published.

$ mosquitto_sub -t 'campus/+/+/+/ota/report' -W 8 | sort -u | wc -l
200    # all 200 rooms reported
```

### 3.4 OTA tamper rejection (P3.2.2)

```
$ venv/bin/python scripts/p3_ota_publisher.py --target room:b01-f01-r101 --version 9.9 --alpha 0.99 --corrupt
[!] payload tampered AFTER signing — receiver should reject
published.

$ docker compose logs app | grep -i tamper
… engine.ota | WARNING | OTA REJECTED on b01-f01-r101 …: hash mismatch (got d26c551b.., expected 13d31ee7..)
```

The room's `alpha` did not change. The bridge picked up `ota/report` and surfaced
`security_alert: OTA_TAMPERING` as a TB client attribute on that device.

### 3.5 Shadow state desired vs reported (P3.1.4)

```
# Operator sets desired state via TB REST
$ curl -X POST …/SHARED_SCOPE -d '{"desired_hvac_mode":"ECO","desired_target_temp":24.5}'
200

# Bridge converts to MQTT cmd
$ tail -1 data/bridge.log
desired -> cmd on campus/b01/f01/r101/cmd: {'hvac_mode':'ECO','target_temp':24.5,'cmd_id':'shared-…'}

# Engine applies, response flows back, bridge sets reported attrs
$ curl …/CLIENT_SCOPE
  reported_hvac_mode = ECO
  reported_target_temp = 24.5
```

Desired = ECO, reported = ECO → in sync.

### 3.6 Unit tests (P3 module coverage)

```
$ venv/bin/python -m unittest discover tests/
Ran 105 tests in 0.474s
OK
```

Phase 3 added 17 tests: hash determinism (3), sign/verify (4), topic targeting (6), apply-to-room (4).

---

## 4. Deliverable Map

| Rubric requirement | File / artefact |
|---|---|
| **3.1.1** Asset hierarchy + server-side attributes | `scripts/p3_provision_metadata.py`, asset rename to `ZC-Main-Campus`, 5 server attrs per room |
| **3.1.1** Relation mapping for aggregation | `scripts/p3_floor_aggregator.py` daemon publishes avg_temperature on each Floor asset |
| **3.1.2** Image Map (floor plan + polygons) | `docs/figures/floor_plan_f01.svg` (placeholder); polygon coordinates align with `coordinates_x` / `coordinates_y` attributes; widget creation is a TB UI step |
| **3.1.3** Interactive overrides | TB device RPC + `desired_*` shared attributes route through bridge → cmd topic |
| **3.1.4** Shadow state | `desired_*` (SHARED_SCOPE) ↔ `reported_*` (CLIENT_SCOPE) round-trip via bridge |
| **3.1.5** Sync status dashboard | `scripts/build_p3_dashboard.py` builds "Phase 3 — Sync & Versioning" |
| **3.2.1** OTA pipeline broadcast / floor / room | `src/engine/ota.py` + `scripts/p3_ota_publisher.py`, MQTT subscribes to all three scopes |
| **3.2.2** SHA-256 + tamper rejection + alert | `canonical_hash` / `verify_payload` reject; bridge emits `security_alert: OTA_TAMPERING` |
| **3.2.3** Fleet versioning | `current_version` client attribute updates on every successful OTA |

---

## 5. How To Reproduce From A Fresh Stack

```bash
# Phase 1+2 stack
./run_all.sh

# Phase 3 metadata + aggregator
venv/bin/python scripts/p3_provision_metadata.py
nohup venv/bin/python scripts/p3_floor_aggregator.py > data/aggregator.log 2>&1 &
disown

# Phase 3 dashboard
venv/bin/python scripts/build_p3_dashboard.py
# → http://localhost:9090/dashboards/<id>

# Test OTA round-trip
venv/bin/python scripts/p3_ota_publisher.py --target broadcast --version 2.0 --alpha 0.015

# Test tamper rejection
venv/bin/python scripts/p3_ota_publisher.py \
    --target room:b01-f01-r101 --version 9.9 --alpha 0.99 --corrupt
docker compose logs app | grep -i tamper

# Test shadow state
TOKEN=$(curl …)
curl -X POST -H "X-Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"desired_hvac_mode":"HEATING","desired_target_temp":27}' \
    http://localhost:9090/api/plugins/telemetry/DEVICE/<id>/SHARED_SCOPE

# All tests
venv/bin/python -m unittest discover tests/    # → 105 OK
```

---

## 6. Manual UI Steps Still Required

These three pieces are dashboard-builder-friendly so I left them as TB-UI steps rather than fragile JSON:

1. **Image Map widget for Floor 01** — TB → Dashboards → `Phase 3 — Sync & Versioning` → **Edit** → **Add widget** → search **"Image Map"**, upload `docs/figures/floor_plan_f01.svg`, set entity alias to "All Devices on Floor 01" (filter by name `*-f01-*`), bind cell color to `temperature`. Click-to-control popup uses TB's **Update Multiple Attributes** widget bound to `desired_*` shared attributes.

2. **TEMP_OUT_OF_RANGE rule chain alarm** — TB → Rule chains → Root Rule Chain → Edit → after **Save Timeseries**, add **Script Filter** with `return msg.temperature > 30 || msg.temperature < 15;` → wire True → **Create Alarm** node (type `TEMP_OUT_OF_RANGE`, severity `MAJOR`, propagate). Same chain can react to `security_alert: OTA_TAMPERING` attribute updates and create a `OTA_TAMPERING` alarm.

3. **Image Map polygon coordinates** — for each room, the polygon center is `(coordinates_x, coordinates_y)` from the asset's SERVER_SCOPE attributes, with corners at ±100 px / ±70 px (cell size). The SVG already shows the layout — drag polygons over each cell.

---

## 7. Files Created/Modified For Phase 3

```
src/engine/ota.py                              NEW   SHA-256 + apply
src/models/room.py                             EDIT  +config_version
src/mqtt/publisher.py                          EDIT  OTA subscribe + handle

scripts/p3_provision_metadata.py               NEW   metadata + rename
scripts/p3_floor_aggregator.py                 NEW   floor avg daemon
scripts/p3_ota_publisher.py                    NEW   OTA CLI
scripts/build_p3_dashboard.py                  NEW   sync dashboard
scripts/bridge_hivemq_to_tb.py                 EDIT  shadow + ota report

tests/test_ota.py                              NEW   17 tests
tests/test_mqtt_node.py                        EDIT  OTA subscribe assertion

docs/phase3_plan.md                            NEW   plan
docs/phase3_report.md                          NEW   THIS FILE
docs/figures/floor_plan_f01.svg                NEW   placeholder image
```

105/105 unit tests passing. Phase 1+2 deliverables remain green.

*End of Phase 3 report.*
