"""Per-CoAP-node DTLS PSK loader.

Reads secrets/coap_psk.json as {"<room_key>": "<hex_psk>", ...}.
Gateways and nodes agree on the same map so DTLS handshakes succeed.
Missing entries yield a zero-length PSK (treated as "no DTLS" by the
CoAP layer when SECURITY_ENABLED is false).
"""

import json
import logging
import os

logger = logging.getLogger("security.psk_store")

DEFAULT_PATH = "secrets/coap_psk.json"

_cache = None


def _path():
    return os.getenv("COAP_PSK_JSON", DEFAULT_PATH)


def load(path=None):
    global _cache
    p = path or _path()
    data = {}
    if not os.path.exists(p):
        logger.warning("coap_psk.json not found at %s — using empty map", p)
        _cache = data
        return data
    with open(p) as f:
        raw = json.load(f)
    for key, hex_psk in raw.items():
        try:
            data[key] = bytes.fromhex(hex_psk)
        except ValueError:
            logger.warning("invalid hex PSK for %s; skipping", key)
    logger.info("Loaded %d CoAP PSKs from %s", len(data), p)
    _cache = data
    return data


def for_room(room):
    if _cache is None:
        load()
    return _cache.get(room.room_key, b"")


def identity_for_room(room):
    return room.room_key.encode("utf-8")
