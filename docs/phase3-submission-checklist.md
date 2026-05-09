# Phase 3 Submission Checklist - Data Persistence

This checklist is based on the PDF section 1.2 (State Persistence) and the Phase 3 note that details are TBD.

| Requirement | Found in repo? | File path | Evidence | What is missing / notes |
| --- | --- | --- | --- | --- |
| Persist room states to lightweight storage (SQLite) | Yes | src/persistence/sqlite_store.py, src/engine/physics_loop.py | DB file data/campus_iot.db exists; PRAGMA shows rooms table | docs/phase3-evidence/04-sqlite-verification.txt |
| Restore previous state on container restart | Yes | src/engine/runtime.py | Logs show "Loaded previous state for 200 rooms" after restart | docs/phase3-evidence/05-restart-persistence-test.txt |
| Avoid full reset after crash | Partial | src/engine/runtime.py | Restart test shows load; no crash simulation | docs/phase3-evidence/05-restart-persistence-test.txt |
| "Last Known Truth" table in SQLite | Yes | src/persistence/sqlite_store.py | init_db creates rooms table; PRAGMA shows expected columns | docs/phase3-evidence/04-sqlite-verification.txt |
| Required columns: room_id, last_temp, last_humidity, hvac_mode, target_temp, last_update | Yes | src/persistence/sqlite_store.py | PRAGMA table_info shows all required columns | docs/phase3-evidence/04-sqlite-verification.txt |
| On startup: if DB empty -> defaults; else load prior values | Partial | src/engine/runtime.py | Load verified on non-empty DB; empty DB path not exercised | docs/phase3-evidence/05-restart-persistence-test.txt |
| Save interval every 30 or 60 seconds (or on command) | Yes | src/engine/physics_loop.py, .env | SQLITE_SAVE_INTERVAL_SECONDS default 30; last_update age ~59s | docs/phase3-evidence/05-restart-persistence-test.txt |
| Dockerized self-hosted environment | Partial | docker-compose.yml | app container running; hivemq failed to start due to port 1883 conflict | docs/phase3-evidence/00-docker-compose-up-error.txt |
| Database/cloud persistence from MQTT/CoAP/ThingsBoard pipeline | Partial | docker-compose.yml | thingsboard + postgres volumes exist | MQTT pipeline not verified in Phase 3 run |

## TODOs for missing items (from this review)
- Stop or reconfigure the container using port 1883 (mytb) and run: docker compose up -d hivemq app
- Optionally verify ThingsBoard/Postgres persistence if required by the updated Phase 3 rubric
