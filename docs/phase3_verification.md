# Phase 3 — Step-by-Step Verification

Walk through each step in order. Each one has an exact command and an exact expected output. If anything diverges, stop and inspect — don't move on.

---

## Step 0 — Stack must be alive

```bash
docker compose ps --format "{{.Name}}: {{.Status}}" | head -15
```

Expect 14 containers all "Up". If not:
```bash
./run_all.sh
```
and wait ~3 minutes.

```bash
pgrep -af bridge_hivemq_to_tb | grep -v /bin/bash
```

Expect one Python process. If empty:
```bash
nohup venv/bin/python scripts/bridge_hivemq_to_tb.py > data/bridge.log 2>&1 < /dev/null &
disown
```

Wait until you see `tb_clients=200`:
```bash
until grep -q "tb_clients=200" data/bridge.log; do sleep 3; done
```

---

## Step 1 — Asset metadata pushed (P3.1.1)

```bash
venv/bin/python scripts/p3_provision_metadata.py 2>&1 | tail -3
```

Expect: `done: 200/200 room assets metadata-tagged`

Sanity-check one asset:

```bash
TOKEN=$(curl -s -X POST http://localhost:9090/api/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"tenant@thingsboard.org","password":"tenant"}' \
  | venv/bin/python -c "import sys,json; print(json.loads(sys.stdin.read())['token'])")
ASSET_ID=$(awk -F, '$1=="b01-f01-r101"{print $7}' data/phase2_registry.csv)
venv/bin/python <<EOF
import httpx
r = httpx.get(f'http://localhost:9090/api/plugins/telemetry/ASSET/$ASSET_ID/values/attributes/SERVER_SCOPE',
              headers={'X-Authorization':'Bearer $TOKEN'})
for row in r.json():
    print(f"  {row['key']:20} = {row['value']}")
EOF
```

Expect 5 keys: `square_footage`, `occupant_capacity`, `coordinates_x`, `coordinates_y`, `room_type`.

---

## Step 2 — Floor aggregator running (P3.1.1)

Start it (or confirm it's already running):
```bash
pgrep -af p3_floor_aggregator | grep -v /bin/bash
```

If empty:
```bash
nohup venv/bin/python scripts/p3_floor_aggregator.py > data/aggregator.log 2>&1 < /dev/null &
disown
```

Wait one cycle (~30 s) then verify:
```bash
until grep -q "posted .* floor summaries" data/aggregator.log; do sleep 5; done
tail -2 data/aggregator.log
```

Expect: `cycle N: posted 10/10 floor summaries`

Confirm Floor 01 has live `avg_temperature`:
```bash
FLOOR1=$(awk -F, '$3==1 {print $8; exit}' data/phase2_registry.csv)
venv/bin/python <<EOF
import httpx
r = httpx.get(f'http://localhost:9090/api/plugins/telemetry/ASSET/$FLOOR1/values/timeseries',
              headers={'X-Authorization':'Bearer $TOKEN'},
              params={'keys':'avg_temperature,avg_humidity,rooms_sampled'})
print(r.text)
EOF
```

Expect a JSON object with `avg_temperature`, `avg_humidity`, `rooms_sampled` (rooms_sampled should be 20).

---

## Step 3 — OTA targeted update to a single room (P3.2.1)

Subscribe to the OTA report topic in one shell, push the OTA from another:

```bash
# Terminal A
mosquitto_sub -h localhost -p 1883 -t 'campus/b01/f01/r101/ota/report' -v -C 1 -W 8

# Terminal B
venv/bin/python scripts/p3_ota_publisher.py \
    --target room:b01-f01-r101 --version 1.5 \
    --alpha 0.025 --beta 0.7
```

Terminal A should print within ~1 second:
```
campus/b01/f01/r101/ota/report {"sensor_id":"b01-f01-r101", ...,
    "rejected": false, "version":"1.5",
    "applied":{"alpha":0.025,"beta":0.7,"config_version":"1.5"}, ...}
```

---

## Step 4 — OTA broadcast to all 200 rooms (P3.2.1)

```bash
# Terminal A — watch how many rooms report back in 8 seconds
timeout 8 mosquitto_sub -h localhost -p 1883 -t 'campus/+/+/+/ota/report' -v 2>&1 \
    | awk '{print $1}' | awk -F/ '{print $4}' | sort -u | wc -l

# Terminal B — fire a broadcast OTA
venv/bin/python scripts/p3_ota_publisher.py --target broadcast --version 2.0 --alpha 0.015
```

Terminal A should print **200** (all rooms reported back).

---

## Step 5 — OTA tamper rejection (P3.2.2)

```bash
# Terminal A — watch the report
mosquitto_sub -h localhost -p 1883 -t 'campus/b01/f01/r101/ota/report' -v -C 1 -W 8

# Terminal B — push a deliberately tampered payload
venv/bin/python scripts/p3_ota_publisher.py \
    --target room:b01-f01-r101 --version 9.9 \
    --alpha 0.99 --corrupt
```

Terminal A should show:
```
... "rejected": true, "reason": "hash mismatch (got ..., expected ...)" ...
```

Engine log:
```bash
docker compose logs app --since 10s | grep -i 'OTA REJECTED'
```

Expect a WARNING line with the `b01-f01-r101` room key and `hash mismatch`.

---

## Step 6 — Tamper alarm in TB (P3.2.2)

```bash
DEVICE=$(awk -F, '$1=="b01-f01-r101"{print $5}' data/phase2_registry.csv)
venv/bin/python <<EOF
import httpx
r = httpx.get(f'http://localhost:9090/api/plugins/telemetry/DEVICE/$DEVICE/values/attributes/CLIENT_SCOPE',
              headers={'X-Authorization':'Bearer $TOKEN'})
for row in r.json():
    if 'security' in row['key'] or 'ota' in row['key']:
        print(f"  {row['key']:25} = {row['value']}")
EOF
```

Expect rows including `security_alert = OTA_TAMPERING`, `ota_rejected = True`, `ota_reason = hash mismatch ...`.

---

## Step 7 — Shadow state — Desired flows down (P3.1.4)

```bash
DEVICE=$(awk -F, '$1=="b01-f01-r101"{print $5}' data/phase2_registry.csv)

# Watch the cmd topic
mosquitto_sub -h localhost -p 1883 -t 'campus/b01/f01/r101/cmd' -v -C 1 -W 8 &
sleep 0.3

# Set desired state via TB REST
venv/bin/python <<EOF
import httpx
r = httpx.post(f'http://localhost:9090/api/plugins/telemetry/DEVICE/$DEVICE/SHARED_SCOPE',
               headers={'X-Authorization':'Bearer $TOKEN'},
               json={'desired_hvac_mode':'HEATING','desired_target_temp':27.5})
print('shared post:', r.status_code)
EOF
wait
```

The `mosquitto_sub` should print:
```
campus/b01/f01/r101/cmd {"hvac_mode":"HEATING","target_temp":27.5,"cmd_id":"shared-..."}
```

This proves the bridge translated the dashboard's desired-state setting into a real MQTT command.

---

## Step 8 — Shadow state — Reported flows back (P3.1.4)

After Step 7, wait ~2 seconds, then:

```bash
venv/bin/python <<EOF
import httpx
for scope in ['SHARED_SCOPE','CLIENT_SCOPE']:
    r = httpx.get(f'http://localhost:9090/api/plugins/telemetry/DEVICE/$DEVICE/values/attributes/{scope}',
                  headers={'X-Authorization':'Bearer $TOKEN'})
    print(f'\\n--- {scope} ---')
    for row in sorted(r.json(), key=lambda x: x['key']):
        if any(k in row['key'] for k in ('desired_','reported_','last_')):
            print(f"  {row['key']:25} = {row['value']}")
EOF
```

Expect:
```
--- SHARED_SCOPE ---
  desired_hvac_mode    = HEATING
  desired_target_temp  = 27.5
--- CLIENT_SCOPE ---
  reported_hvac_mode   = HEATING
  reported_target_temp = 27.5
  last_cmd_id          = shared-...
```

Desired matches Reported → in sync.

---

## Step 9 — Phase 3 dashboard exists in TB (P3.1.5)

```bash
venv/bin/python <<EOF
import httpx
r = httpx.get('http://localhost:9090/api/tenant/dashboards',
              headers={'X-Authorization':'Bearer $TOKEN'},
              params={'pageSize':100,'page':0})
for d in r.json()['data']:
    if 'Phase 3' in d['title']:
        print(f"{d['id']['id']}  {d['title']}")
EOF
```

Expect at least one row with title `Phase 3 — Sync & Versioning`.

Open it in a browser:
```
http://localhost:9090/dashboards/<id>
```

You should see one widget — the **Shadow Sync Status** entities table with columns Active, Desired HVAC, Reported HVAC, Desired Target, Reported Target, Version, Security. Devices show green Active markers; rooms you just OTA-bumped show their new Version (e.g. `2.0`).

---

## Step 10 — Versioning attribute populated (P3.2.3)

After running Step 4 (broadcast version 2.0):

```bash
venv/bin/python <<EOF
import httpx, csv
with open('data/phase2_registry.csv') as f:
    rows = list(csv.DictReader(f))[:5]
for row in rows:
    r = httpx.get(f"http://localhost:9090/api/plugins/telemetry/DEVICE/{row['device_id']}/values/attributes/CLIENT_SCOPE",
                  headers={'X-Authorization':'Bearer $TOKEN'})
    cv = next((x['value'] for x in r.json() if x['key']=='current_version'), None)
    print(f"  {row['device_name']:30}  current_version = {cv}")
EOF
```

Expect each row to show `current_version = 2.0` (the broadcast version).

---

## Step 11 — All unit tests still green

```bash
venv/bin/python -m unittest discover tests/ 2>&1 | tail -3
```

Expect: `Ran 105 tests in N.NNNs   OK`

---

## If Anything Fails

| Symptom | Fix |
|---|---|
| Step 0 — bridge dead | Restart per Step 0 commands |
| Step 1 — 401 from TB | Token expired; re-export `TOKEN=...` |
| Step 2 — `posted 0/10` | Engine isn't publishing telemetry — `docker compose restart app` |
| Step 4 — fewer than 200 reports | Some shadow clients missed; rerun with `-W 15` |
| Step 5 — payload accepted (no rejection) | Make sure you used `--corrupt` |
| Step 7 — bridge didn't translate | bridge is dead: `pkill -f bridge_hivemq_to_tb && nohup venv/bin/python scripts/bridge_hivemq_to_tb.py > data/bridge.log 2>&1 < /dev/null & disown` |
| Step 9 — no dashboard | `venv/bin/python scripts/build_p3_dashboard.py` |
| Step 11 — test failure | Reread error output; the tests are deterministic |

---

## Final Cheat Sheet — One-Liners

```bash
# Push OTA to whole fleet
venv/bin/python scripts/p3_ota_publisher.py --target broadcast --version 3.0 --alpha 0.012 --beta 0.45

# Push OTA only to floor 5
venv/bin/python scripts/p3_ota_publisher.py --target floor:05 --version 3.0 --sensor-drift-rate 0.05

# Demo tamper detection
venv/bin/python scripts/p3_ota_publisher.py --target room:b01-f01-r101 --version 99 --alpha 9 --corrupt

# Set desired state for a device
DEVICE=$(awk -F, '$1=="b01-f01-r101"{print $5}' data/phase2_registry.csv)
venv/bin/python -c "
import httpx
r = httpx.post('http://localhost:9090/api/plugins/telemetry/DEVICE/$DEVICE/SHARED_SCOPE',
               headers={'X-Authorization':'Bearer $TOKEN'},
               json={'desired_hvac_mode':'COOLING','desired_target_temp':18})
print(r.status_code)
"

# Show desired vs reported for a device
venv/bin/python -c "
import httpx
for scope in ['SHARED_SCOPE','CLIENT_SCOPE']:
    r = httpx.get(f'http://localhost:9090/api/plugins/telemetry/DEVICE/$DEVICE/values/attributes/{scope}',
                  headers={'X-Authorization':'Bearer $TOKEN'})
    print(scope); [print(f' {r[\"key\"]}={r[\"value\"]}') for r in r.json()]
"
```
