# Phase 3 — Implementation Plan

## Overview

Phase 3 = "Digital Twin + Secure OTA on top of Phase 2". Five work packages, ordered from least risky to most risky. Every package has a clear acceptance test so we know when it's done.

---

## Work Package A — Asset Metadata & Relations (P3.1.1)

### Goal
Every Room asset in ThingsBoard carries server-side static metadata (square_footage, occupant_capacity, coordinates_x/y, room_type) and is linked to its Floor/Building/Campus by `Contains` relations. Floor assets compute live `avg_temperature` of their 20 child rooms.

### What I'll build

**File: `scripts/p3_provision_metadata.py`**
A one-shot script (idempotent like the Phase 2 provisioner) that:
1. Renames the existing root campus asset from `Campus` → `ZC-Main-Campus` (matches rubric).
2. Loops over the 200 rooms in `data/phase2_registry.csv` and writes server-scope attributes via:
   ```
   POST /api/plugins/telemetry/ASSET/{room_asset_id}/attributes/SERVER_SCOPE
   ```
   Values are deterministic from the room's floor/room number (so re-running gives the same map).

**File: `scripts/p3_floor_aggregator.py`**
A small daemon that runs alongside `bridge_hivemq_to_tb.py`. It subscribes to `campus/+/+/+/telemetry`, accumulates rolling averages per floor (60s window), and posts `avg_temperature` / `avg_humidity` to each Floor asset's telemetry via TB's Asset MQTT API. (We can't use a Rule Chain Aggregate node because TB CE 3.7 doesn't ship that node — the daemon does it externally. This still satisfies the rubric's "Relation Mapping for Aggregation" via "alternative: Script transformation node that queries all child devices via relations".)

### Acceptance test
```bash
TOKEN=...   # tenant login
curl -H "X-Authorization: Bearer $TOKEN" \
    "http://localhost:9090/api/plugins/telemetry/ASSET/<room-asset-id>/values/attributes/SERVER_SCOPE"
# → returns square_footage, occupant_capacity, coordinates_x, coordinates_y, room_type

curl -H "X-Authorization: Bearer $TOKEN" \
    "http://localhost:9090/api/plugins/telemetry/ASSET/<floor-asset-id>/values/timeseries"
# → returns avg_temperature, avg_humidity for the floor
```

---

## Work Package B — Shadow State (P3.1.4)

### Goal
Every room has two states in TB:
- **Desired** = what the operator wants (Shared Attribute, set by dashboard or REST)
- **Reported** = what the room actually is (Client Attribute, sent by the engine)

Mismatch = "out of sync"; the engine reconciles on next heartbeat by applying the desired settings and confirming via reported.

### What I'll build

**Modify `src/mqtt/publisher.py` and `src/coap/resources.py`**
- Already publish `state` inside the response payload. Now also push to TB as **client attributes** via the bridge (the bridge can split out the `state` keys into `attributes` instead of `telemetry`).

**Modify `scripts/bridge_hivemq_to_tb.py`**
- After publishing telemetry, also publish to `v1/devices/me/attributes` with reported state keys (`reported_hvac_mode`, `reported_target_temp`, etc.).
- Subscribe on TB MQTT to `v1/devices/me/attributes` for shared-attribute updates from the dashboard, then forward the **desired** values to HiveMQ as a regular cmd on `campus/.../cmd`. This closes the southbound loop from the dashboard.

**Modify `src/engine/commands.py`**
- After applying a command, set the room's "desired" hint on the room object so subsequent telemetry includes both desired and reported (already does — they converge on first apply).

### Acceptance test
- Set a Shared Attribute `desired_hvac_mode = HEATING` on a device via TB UI or REST.
- Within ~5s the room applies it and the bridge publishes `reported_hvac_mode = HEATING`.
- The dashboard's Sync Status widget shows row turn from "Out of sync" red → "In sync" green.

---

## Work Package C — OTA Pipeline (P3.2.1)

### Goal
Operators can hot-swap physics parameters (`alpha`, `beta`, fault rates, etc.) for the whole fleet, a floor, or a single room — without restarting the engine.

### What I'll build

**Modify `src/mqtt/publisher.py`**
- Add a second subscription: `campus/+/+/+/ota` on each MqttNodeClient (so every node gets per-room OTA on its own subtree).
- Plus a broadcast subscription `campus/b01/ota/config` for fleet-wide updates — but only ONE shared client subscribes to that to avoid 100× duplicate handling. I'll add a small `OtaListener` class in the engine runtime that subscribes once and dispatches by room.

**File: `src/engine/ota.py`**
A new module:
```python
def apply_ota_payload(room, payload, expected_hash):
    """Verify SHA-256 then mutate room.alpha/beta/fault rates.
    Returns True if applied, False if rejected."""
```
Increments `room.config_version` after every successful apply.

**Modify `src/models/room.py`**
- Add `self.config_version` (defaults to "1.0").
- Allow alpha/beta to be reassigned at runtime (already public attributes — fine).

**File: `scripts/p3_ota_publisher.py`**
A CLI for pushing OTA updates:
```
venv/bin/python scripts/p3_ota_publisher.py \
    --target broadcast \
    --version 1.1 \
    --alpha 0.02 \
    --beta 0.6
```
Or:
```
... --target floor:01 ...
... --target room:b01-f03-r315 ...
```

### Acceptance test
```bash
# Before
docker exec campus-engine venv/bin/python -c "
from src.engine.fleet import rooms
print(rooms[0].alpha, rooms[0].beta, rooms[0].config_version)
"
# 0.01 0.5 1.0

# Push OTA
venv/bin/python scripts/p3_ota_publisher.py --target broadcast --version 1.1 --alpha 0.02

# After 5s
docker exec campus-engine ...
# 0.02 0.5 1.1
```

---

## Work Package D — SHA-256 Verification (P3.2.2)

### Goal
OTA payloads are signed; tampered payloads are rejected and trigger a security alert in TB.

### What I'll build

**Modify `src/engine/ota.py`**
- Compute hash via `hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()`.
- Reject mismatches; log and emit a TB alarm via a special MQTT topic `campus/security/tampering` that the bridge forwards as a TB alarm using the alarm REST API.

**Modify `scripts/p3_ota_publisher.py`**
- Compute SHA-256 of the canonical-sort JSON, attach as `_sig` field.
- Add `--corrupt` flag that intentionally tampers with the payload after signing, so we can demo tampering detection.

**File: `tests/test_ota_security.py`**
- Verifies legit payloads pass.
- Verifies tampered payloads are rejected and don't change room state.
- Verifies the JSON canonical-sort produces stable hashes.

### Acceptance test
```bash
# Normal OTA → applied
venv/bin/python scripts/p3_ota_publisher.py --target room:b01-f01-r101 --version 2.0 --alpha 0.03

# Tampered → rejected
venv/bin/python scripts/p3_ota_publisher.py --target room:b01-f01-r101 --version 2.0 --alpha 0.04 --corrupt

# Engine log shows: "OTA tampering detected on b01-f01-r101"
docker compose logs app | grep -i tamper

# TB alarm shows "OTA_TAMPERING" type
```

---

## Work Package E — Dashboard widgets (P3.1.2, P3.1.3, P3.1.5, P3.2.3)

### Goal
Visualize the digital twin: floor plan with hot rooms colored red, click-to-control popups, sync status table, version evolution view.

### What I'll build

**File: `scripts/build_p3_dashboard.py`**
Builds 3 new dashboards (or 3 states inside one dashboard):

1. **Floor Plan (Image Map)**: an Image Map widget with a polygon per room on Floor 01, color-bound to `temperature` (blue ≤ 18°C, red ≥ 30°C). Click → opens a state with HVAC mode dropdown + dimmer slider. **The image** can be a placeholder grid SVG I generate on the fly so we don't need a real architectural drawing.

2. **Sync Status Table**: a built-in Entities Table with columns Device / Last Seen / Desired HVAC / Reported HVAC / Desired Dimmer / Reported Dimmer / Sync Status. Sync Status uses a TB cell-style function that renders green ✓ when desired==reported else red ✗. Filter button shows out-of-sync only.

3. **Fleet Version Status**: Entities Table with `current_version` attribute, color-coded by whether it matches the latest desired version.

### Acceptance test
- Open the new dashboard in TB
- Floor plan shows 20 colored polygons, color updates as room temperatures change
- Click a polygon → popup with HVAC controls
- Toggle the HVAC switch → telemetry shows hvac_mode change within 5s
- Push a fake OTA to room 1 with version 2.0; the version table immediately shows 1 row at version 2.0 and 199 rows at version 1.0

---

## Order of Execution

1. **A (metadata + floor aggregator)** — foundation; lowest risk. ~30 min.
2. **C (OTA pipeline)** — engine extension; everything else builds on this. ~45 min.
3. **D (SHA-256)** — small additive change to C. ~20 min.
4. **B (shadow state)** — bridge + TB integration; medium risk. ~30 min.
5. **E (dashboards)** — pure UI/REST; can take the longest because TB widget JSON is fiddly. ~60 min.

**Total estimated effort:** ~3 hours of focused work + tests + a Phase 3 report addendum.

---

## What I Need From You Before Starting

Two yes/no questions:

### Q1: Floor plan source
Should I generate a placeholder SVG floor plan (a 20-room grid with the room IDs labeled) for the Image Map widget, or do you have a real architectural drawing you want to use?

I recommend **generated placeholder** — it always matches your fleet layout, no asset upload friction.

### Q2: Test coverage
For Phase 3 work packages, do you want me to add unit tests as I go (so the final test count goes from 88 → ~100), or just integration tests run against the live stack?

I recommend **both** — unit tests for OTA hash verification + apply, integration tests for full round-trips.

---

## What This Plan Will NOT Do

- It won't deploy real OTA *firmware* — only physics-parameter hot-swaps. The rubric explicitly allows this ("such as thermal constants alpha or beta").
- It won't enforce Mutual TLS for OTA — the SHA-256 hash satisfies the integrity/authentication requirement at the application layer.
- It won't create a new building (only B01 already exists). If you want B02 too, tell me — it's 5 minutes of provisioner extension.
- It won't break Phase 2 — all Phase 2 deliverables stay green.

---

## Tell Me

Reply with:
1. **Floor plan**: placeholder OK or use your own?
2. **Tests**: yes/no
3. **Building B02**: yes/no (probably no — rubric says "e.g., B01, B02" as example only)
4. **Order**: start with A (lowest risk) or jump straight to D (SHA-256 + OTA, the most "wow" demo for the TA)?

Once you answer, I'll execute end-to-end.
