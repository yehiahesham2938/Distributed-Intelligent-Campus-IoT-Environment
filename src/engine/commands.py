"""Shared command application logic.

Both MQTT node callbacks and CoAP actuator resources validate and apply
incoming commands via apply_command(). Keeps field validation in one
place and guarantees identical semantics across protocols.
"""

import json
import logging
import time

logger = logging.getLogger("engine.commands")

VALID_HVAC_MODES = ("ON", "OFF", "ECO", "COOLING", "HEATING")


def parse_payload(payload):
    """Decode a command payload (bytes or str) into a dict; None on failure."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    if not isinstance(payload, str):
        return None
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def apply_command(room, data):
    """Apply a validated command dict to a Room. Returns the set of fields
    that were actually changed so the caller can log / ack meaningfully.
    """
    applied = {}

    if "hvac_mode" in data:
        mode = data.get("hvac_mode")
        if mode in VALID_HVAC_MODES:
            if mode == "ON":
                mode = "HEATING" if room.temperature < room.target_temp else "COOLING"
            room.hvac_mode = mode
            applied["hvac_mode"] = mode
            logger.info("cmd %s hvac_mode -> %s", room.room_key, mode)
        else:
            logger.warning("invalid hvac_mode %r for %s", mode, room.room_key)

    if "target_temp" in data:
        try:
            target = float(data["target_temp"])
        except (TypeError, ValueError):
            logger.warning("invalid target_temp for %s", room.room_key)
        else:
            if 15.0 <= target <= 50.0:
                room.target_temp = target
                applied["target_temp"] = target
                logger.info("cmd %s target_temp -> %.1f", room.room_key, target)
            else:
                logger.warning("target_temp %.1f out of range for %s", target, room.room_key)

    if "lighting_dimmer" in data:
        try:
            dimmer = int(data["lighting_dimmer"])
        except (TypeError, ValueError):
            logger.warning("invalid lighting_dimmer for %s", room.room_key)
        else:
            if 0 <= dimmer <= 100:
                room.lighting_dimmer = dimmer
                applied["lighting_dimmer"] = dimmer
                logger.info("cmd %s lighting_dimmer -> %d", room.room_key, dimmer)
            else:
                logger.warning("lighting_dimmer %d out of range for %s", dimmer, room.room_key)

    return applied


def build_response(room, cmd_id, applied):
    return {
        "sensor_id": room.room_key,
        "cmd_id": cmd_id,
        "timestamp": int(time.time()),
        "applied": applied,
        "state": {
            "hvac_mode": room.hvac_mode,
            "target_temp": room.target_temp,
            "lighting_dimmer": room.lighting_dimmer,
            "temperature": round(room.temperature, 1),
        },
    }
