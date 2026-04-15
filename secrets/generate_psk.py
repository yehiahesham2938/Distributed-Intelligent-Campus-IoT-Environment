"""Generate secrets/coap_psk.json with one PSK per CoAP node.

Runs against the Phase 2 fleet layout (rooms 11..20 on each of 10
floors = 100 CoAP rooms). Idempotent: preserves existing entries
unless FORCE=1 is set in the environment, so re-running does not break
an active deployment.

Usage:  venv/bin/python secrets/generate_psk.py
"""

import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.engine.fleet import create_room_fleet  # noqa: E402


OUT = Path(__file__).resolve().parent / "coap_psk.json"
FORCE = os.getenv("FORCE") == "1"


def main():
    existing = {}
    if OUT.exists() and not FORCE:
        with OUT.open() as f:
            existing = json.load(f)

    fleet = create_room_fleet()
    out = dict(existing)
    added = 0
    for room in fleet:
        if room.protocol != "coap":
            continue
        if room.room_key in out:
            continue
        out[room.room_key] = secrets.token_hex(16)
        added += 1

    with OUT.open("w") as f:
        json.dump(out, f, indent=2, sort_keys=True)

    print(f"wrote {OUT} — {len(out)} PSKs ({added} new)")


if __name__ == "__main__":
    main()
