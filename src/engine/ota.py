"""Phase 3.2 — OTA configuration application + SHA-256 verification.

Payload contract (one MQTT message per update):

    {
        "version": "1.1",
        "params": {"alpha": 0.02, "beta": 0.6},
        "_sig": "<sha256 hex of canonical(payload-without-_sig)>"
    }

The hash is calculated over the payload with `_sig` removed and keys
sorted alphabetically (json.dumps(..., sort_keys=True)). The receiving
engine recomputes the hash and rejects mismatches.

Targets are encoded in the topic, not in the payload:
    campus/b01/ota/config           — broadcast (every room subscribes)
    campus/b01/f05/ota              — floor target (rooms on f05 only)
    campus/b01/f03/r315/ota         — single room

The room knows its own room_key, so it can simply check whether a topic
belongs to its scope.
"""

import hashlib
import json
import logging
import time

logger = logging.getLogger("engine.ota")

# Whitelist of physics/fault parameters that can be hot-swapped.
APPLIABLE_PARAMS = {
    "alpha", "beta",
    "sensor_drift_rate", "frozen_sensor_rate",
    "telemetry_delay_rate", "node_dropout_rate",
    "sensor_drift_step_max",
    "telemetry_delay_min_seconds", "telemetry_delay_max_seconds",
}


def canonical_hash(data):
    """SHA-256 of JSON with sort_keys=True, _sig stripped."""
    if isinstance(data, dict):
        clean = {k: v for k, v in data.items() if k != "_sig"}
    else:
        clean = data
    blob = json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def sign_payload(data):
    """Return a copy of `data` with a `_sig` field set to its canonical hash."""
    if not isinstance(data, dict):
        raise TypeError("payload must be a dict")
    out = dict(data)
    out.pop("_sig", None)
    out["_sig"] = canonical_hash(out)
    return out


def verify_payload(data):
    """Return (ok, reason). reason explains why if ok is False."""
    if not isinstance(data, dict):
        return False, "payload not a dict"
    sig = data.get("_sig")
    if not sig:
        return False, "missing _sig"
    expected = canonical_hash(data)
    if sig != expected:
        return False, f"hash mismatch (got {sig[:8]}.., expected {expected[:8]}..)"
    if "version" not in data:
        return False, "missing version"
    if "params" not in data or not isinstance(data["params"], dict):
        return False, "missing or invalid params"
    return True, "ok"


def topic_targets_room(topic, room):
    """Return True if an OTA topic targets this specific room.

    Recognized topics:
        campus/b01/ota/config            — broadcast
        campus/b01/fNN/ota               — floor scope
        campus/b01/fNN/rRRR/ota          — single room
    """
    parts = topic.split("/")
    if len(parts) < 3 or parts[0] != "campus":
        return False
    building = parts[1]
    if building != room.building_id:
        return False

    # broadcast: campus/b01/ota/config
    if len(parts) == 4 and parts[2] == "ota" and parts[3] == "config":
        return True

    # floor: campus/b01/fNN/ota
    if len(parts) == 4 and parts[3] == "ota":
        try:
            floor_id = int(parts[2][1:])
        except ValueError:
            return False
        return floor_id == room.floor_id

    # single room: campus/b01/fNN/rRRR/ota
    if len(parts) == 5 and parts[4] == "ota":
        try:
            floor_id = int(parts[2][1:])
            room_number = int(parts[3][1:])
        except ValueError:
            return False
        target_room_number = room.floor_id * 100 + room.room_id
        return floor_id == room.floor_id and room_number == target_room_number

    return False


def apply_to_room(room, payload, topic="<unknown>"):
    """Apply a verified OTA payload to a Room. Returns dict of changes.

    The room object must have public attributes for each whitelisted
    param (alpha, beta, sensor_drift_rate, ...). Unknown keys are
    ignored with a warning; this is forward-compatible because new
    rooms could ship newer software than the OTA schema.
    """
    ok, reason = verify_payload(payload)
    if not ok:
        logger.warning(
            "OTA REJECTED on %s topic=%s: %s",
            room.room_key, topic, reason
        )
        return {"applied": {}, "rejected": True, "reason": reason}

    params = payload.get("params", {})
    applied = {}
    skipped = []
    for key, value in params.items():
        if key not in APPLIABLE_PARAMS:
            skipped.append(key)
            continue
        try:
            if isinstance(getattr(room, key, None), int):
                value = int(value)
            else:
                value = float(value)
        except (TypeError, ValueError):
            skipped.append(key)
            continue
        setattr(room, key, value)
        applied[key] = value

    new_version = str(payload.get("version", "?"))
    setattr(room, "config_version", new_version)
    applied["config_version"] = new_version

    logger.info(
        "OTA APPLIED on %s topic=%s version=%s applied=%s skipped=%s",
        room.room_key, topic, new_version, applied, skipped or "[]"
    )
    return {
        "applied": applied,
        "skipped": skipped,
        "rejected": False,
        "version": new_version,
        "applied_at": int(time.time()),
    }
