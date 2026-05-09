# Phase 3 Verification Evidence - Data Persistence

Date: 2026-05-09
Scope: Phase 3 persistence only (SQLite state retention).

## Docker compose services
Command:
```
docker compose config --services
```
Output:
```
hivemq
app
gateway-floor-03
gateway-floor-10
gateway-floor-07
thingsboard-postgres
thingsboard
gateway-floor-02
gateway-floor-05
gateway-floor-08
gateway-floor-09
gateway-floor-01
gateway-floor-04
gateway-floor-06
```
Evidence: docs/phase3-evidence/00-docker-compose-services.txt

## Minimal stack attempt (failed)
Command:
```
docker compose up -d hivemq app
```
Result:
```
Bind for 0.0.0.0:1883 failed: port is already allocated
```
Evidence:
- docs/phase3-evidence/00-docker-compose-up-error.txt
- docs/phase3-evidence/00-port-conflict.txt (port 1883 in use by mytb)

## App-only start (persistence verification)
Command:
```
docker compose up -d --no-deps app
```
Status:
```
campus-engine   ...   Up
```
Evidence: docs/phase3-evidence/01-docker-compose-ps.txt

## App logs (persistence load)
Key lines (post-restart logs):
```
Initializing database...
Database initialized at data/campus_iot.db
Loaded previous state for 200 rooms
```
Evidence: docs/phase3-evidence/05-restart-persistence-test.txt
Note: MQTT nodes fail to connect because HiveMQ is not running.

## SQLite DB location
```
C:\Users\asus\Documents\GitHub\Distributed-Intelligent-Campus-IoT-Environment\data\campus_iot.db
```
Evidence: docs/phase3-evidence/03-database-file-path.txt

## SQLite schema and sample rows
Evidence (tables, schema, sample rows):
- docs/phase3-evidence/04-sqlite-verification.txt

## Restart persistence test
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

## Screenshots
No GUI screenshots captured in this run. If required, capture:
- SQLite query output showing the rooms table schema and a sample row.
- App logs showing "Loaded previous state" after a restart.
- File explorer showing data/campus_iot.db.

## Evidence files
- docs/phase3-evidence/00-docker-compose-services.txt
- docs/phase3-evidence/00-docker-compose-up-error.txt
- docs/phase3-evidence/00-port-conflict.txt
- docs/phase3-evidence/01-docker-compose-ps.txt
- docs/phase3-evidence/02-app-persistence-logs.txt
- docs/phase3-evidence/03-database-file-path.txt
- docs/phase3-evidence/04-sqlite-verification.txt
- docs/phase3-evidence/05-restart-persistence-test.txt
