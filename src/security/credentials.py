"""Per-MQTT-node username/password loader.

Reads secrets/mqtt_credentials.csv (room_key,username,password). Falls
back to anonymous credentials if the file is missing or a room has no
entry, which is useful for local development against a broker with
allow_anonymous true.
"""

import csv
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("security.credentials")

DEFAULT_PATH = "secrets/mqtt_credentials.csv"


@dataclass
class MqttCredentials:
    room_key: str
    username: str
    password: str


_cache = None


def _path():
    return os.getenv("MQTT_CREDENTIALS_CSV", DEFAULT_PATH)


def load(path=None):
    global _cache
    p = path or _path()
    creds = {}
    if not os.path.exists(p):
        logger.warning("mqtt_credentials.csv not found at %s — using anonymous", p)
        _cache = creds
        return creds
    with open(p, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row["room_key"].strip()
            creds[key] = MqttCredentials(
                room_key=key,
                username=row["username"].strip(),
                password=row["password"].strip(),
            )
    logger.info("Loaded %d MQTT credentials from %s", len(creds), p)
    _cache = creds
    return creds


def for_room(room):
    if _cache is None:
        load()
    entry = _cache.get(room.room_key)
    if entry is not None:
        return entry
    return MqttCredentials(room_key=room.room_key, username="", password="")
