# Phase 3 Report - Data Persistence

Zewail City of Science, Technology and Innovation
University of Science and Technology
School of Computational Sciences and Artificial Intelligence
SWAPD453 - Spring 2026
IoT App Devs
Distributed Intelligent Campus IoT Environment
Student names and IDs: <fill here>
Date: 2026-05-09

## Phase 3 objective
Phase 3 focuses on data persistence. The PDF notes Phase 3 details are TBD, so this report follows the explicit state persistence requirements in section 1.2. Phase 3 builds on the previous phases by keeping the simulated room state stable across restarts.

## What was implemented
- SQLite persistence for room state in the engine.
- A "rooms" table that stores the last known truth for each room.
- Startup logic that loads previous state if the DB is not empty.
- Periodic save points every 30 seconds (configurable).

## Database and persistence design
- Database file: data/campus_iot.db (default path).
- Table: rooms.
- One row per room using a unique room_id (example: b01-f01-r101).
- Columns stored:
  - room_id (text, primary key)
  - last_temp (float)
  - last_humidity (float)
  - hvac_mode (text)
  - target_temp (float)
  - last_update (integer, unix timestamp)
- Save interval: SQLITE_SAVE_INTERVAL_SECONDS (default 30).

## How the data flows
1. The engine boots and initializes SQLite.
2. If the DB is empty, default values are inserted for all rooms.
3. If the DB has data, previous state is loaded into Room objects.
4. During the physics loop, each room is saved to SQLite every 30 seconds.
5. After a crash or restart, the last saved values are loaded and the simulation resumes from the saved state.

## Docker and run instructions (Phase 3 minimum)
From the repo root:

```
docker compose up -d hivemq app
```

If port 1883 is already in use, start only the app for persistence testing:

```
docker compose up -d --no-deps app
```

Optional checks:

```
docker compose logs app --tail 50
docker compose ps
```

To stop:

```
docker compose down
```

## Testing and verification
This run used Docker Desktop. The minimal stack failed to start because port 1883 was already allocated by another container. I started the app without dependencies to validate SQLite persistence.

### Compose services list
Command:
```
docker compose config --services
```
Evidence: docs/phase3-evidence/00-docker-compose-services.txt

### Attempt to run the minimal stack (failed)
Command:
```
docker compose up -d hivemq app
```
Result: Bind for 0.0.0.0:1883 failed: port is already allocated
Evidence: docs/phase3-evidence/00-docker-compose-up-error.txt
Port owner evidence: docs/phase3-evidence/00-port-conflict.txt

### App-only start (persistence verification)
Command:
```
docker compose up -d --no-deps app
```
Status: campus-engine running
Evidence: docs/phase3-evidence/01-docker-compose-ps.txt

### App logs - persistence load
Key lines (post-restart logs):
```
Initializing database...
Database initialized at data/campus_iot.db
Loaded previous state for 200 rooms
```
Evidence: docs/phase3-evidence/05-restart-persistence-test.txt
Note: MQTT connection errors appear because HiveMQ is not running.

### SQLite DB evidence
Command:
```
python -c "import sqlite3; conn=sqlite3.connect('data/campus_iot.db'); cur=conn.execute('SELECT COUNT(*) FROM rooms'); print('rooms count:', cur.fetchone()[0]); schema=conn.execute('PRAGMA table_info(rooms)').fetchall(); print('columns:', [c[1] for c in schema]); row=conn.execute('SELECT room_id, last_temp, last_humidity, hvac_mode, target_temp, last_update FROM rooms ORDER BY room_id LIMIT 1').fetchone(); print('sample row:', row); conn.close()"
```
Output:
```
rooms count: 200
columns: ['room_id', 'last_temp', 'last_humidity', 'hvac_mode', 'target_temp', 'last_update']
sample row: ('b01-f01-r101', 19.942911120770848, 55.4, 'COOLING', 20.0, 1776528691)
```
Evidence: docs/phase3-evidence/04-sqlite-verification.txt

### Restart persistence test
Pre-restart snapshot:
```
count: 200
max_last_update: 1778345388
age_seconds: 41
```
Post-restart snapshot:
```
count: 200
max_last_update: 1778345411
age_seconds: 59
```
Evidence: docs/phase3-evidence/05-restart-persistence-test.txt

## Verification evidence
- docs/phase3-verification-evidence.md (combined summary)
- docs/phase3-evidence/00-docker-compose-services.txt
- docs/phase3-evidence/00-docker-compose-up-error.txt
- docs/phase3-evidence/00-port-conflict.txt
- docs/phase3-evidence/01-docker-compose-ps.txt
- docs/phase3-evidence/02-app-persistence-logs.txt
- docs/phase3-evidence/03-database-file-path.txt
- docs/phase3-evidence/04-sqlite-verification.txt
- docs/phase3-evidence/05-restart-persistence-test.txt

## Evidence section (screenshots)
No GUI screenshots were captured in this run. If required, capture:
- SQLite query output showing the rooms table and a sample row.
- App logs that show "Loaded previous state" after a restart.
- The data/campus_iot.db file in the repo.

## Known limitations
- HiveMQ could not start because port 1883 was already allocated by another container (see evidence). MQTT nodes failed to connect, so full MQTT pipeline testing was not possible in this run.
- No GUI screenshots were captured; only terminal evidence is included.
- The PDF says Phase 3 details are TBD; this report only covers the explicit state persistence requirements.

## Final submission checklist
See docs/phase3-submission-checklist.md.
