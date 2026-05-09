"""Phase 3.1.1 — Provision static metadata onto every Room asset in TB.

Adds five server-scope attributes per Room:
    square_footage      — m^2 (deterministic from floor & room number)
    occupant_capacity   — int
    coordinates_x       — pixel x on the floor plan
    coordinates_y       — pixel y on the floor plan
    room_type           — lecture_hall | lab | office | corridor

Also renames the existing root campus asset from "Campus" to
"ZC-Main-Campus" to match the rubric naming.

Idempotent:
    * Re-running overwrites attributes with the same deterministic values.
    * Asset rename is a no-op if already renamed.

Env: TB_URL / TB_USERNAME / TB_PASSWORD (defaults to localhost dev creds)
"""

import csv
import logging
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_CSV = ROOT / "data" / "phase2_registry.csv"

TB_URL = os.getenv("TB_URL", "http://localhost:9090")
TB_USERNAME = os.getenv("TB_USERNAME", "tenant@thingsboard.org")
TB_PASSWORD = os.getenv("TB_PASSWORD", "tenant")

ROOM_TYPES = ["lecture_hall", "lab", "office", "corridor"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | p3.metadata | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("p3.metadata")


def _login(client):
    r = client.post(
        f"{TB_URL}/api/auth/login",
        json={"username": TB_USERNAME, "password": TB_PASSWORD},
    )
    r.raise_for_status()
    token = r.json()["token"]
    client.headers["X-Authorization"] = f"Bearer {token}"


def _build_metadata(room_key, floor_id):
    """Deterministic per-room metadata so re-runs are stable."""
    parts = room_key.split("-")
    room_num = int(parts[2][1:])
    local_room_idx = (room_num - floor_id * 100)

    # Deterministic-but-varied:
    #   floor_id seeds the row, local_room_idx the column on a 5x4 grid
    col = (local_room_idx - 1) % 5
    row = (local_room_idx - 1) // 5

    # Room types cycle with the room index but are stable per room.
    room_type = ROOM_TYPES[local_room_idx % len(ROOM_TYPES)]

    # Square footage scales 30..70 m^2 deterministically
    square_footage = 30 + ((local_room_idx * 7) % 40)
    occupant_capacity = max(2, square_footage // 2)

    # Floor-plan grid: 5 cols x 4 rows. Cell 200x140 px, top-left at (60,40).
    coordinates_x = 60 + col * 200 + 100  # center of the cell
    coordinates_y = 40 + row * 140 + 70

    return {
        "square_footage": square_footage,
        "occupant_capacity": occupant_capacity,
        "coordinates_x": coordinates_x,
        "coordinates_y": coordinates_y,
        "room_type": room_type,
    }


def _rename_campus(client):
    """Ensure exactly one campus asset named 'ZC-Main-Campus'.

    Cases:
      * only 'Campus' exists -> rename it.
      * only 'ZC-Main-Campus' exists -> no-op.
      * both exist -> delete the orphan 'Campus' (canonical asset wins).
      * neither exists -> warn.
    """
    r = client.get(
        f"{TB_URL}/api/tenant/assets",
        params={"pageSize": 50, "page": 0, "textSearch": "Campus"},
    )
    r.raise_for_status()
    rows = r.json().get("data", [])
    by_name = {row.get("name"): row for row in rows}

    canonical = by_name.get("ZC-Main-Campus")
    legacy = by_name.get("Campus")

    if canonical and legacy:
        legacy_id = legacy["id"]["id"]
        r2 = client.delete(f"{TB_URL}/api/asset/{legacy_id}")
        r2.raise_for_status()
        logger.info("deleted orphan 'Campus' asset %s (canonical already present)", legacy_id)
        return
    if canonical:
        logger.info("campus already named ZC-Main-Campus")
        return
    if legacy:
        legacy_id = legacy["id"]["id"]
        updated = dict(legacy)
        updated["name"] = "ZC-Main-Campus"
        r2 = client.post(f"{TB_URL}/api/asset", json=updated)
        r2.raise_for_status()
        logger.info("renamed Campus -> ZC-Main-Campus (%s)", legacy_id)
        return
    logger.warning("no campus asset found to rename")


def _post_attrs(client, asset_id, attrs):
    r = client.post(
        f"{TB_URL}/api/plugins/telemetry/ASSET/{asset_id}/attributes/SERVER_SCOPE",
        json=attrs,
    )
    r.raise_for_status()


def main():
    if not REGISTRY_CSV.exists():
        logger.error("registry not found at %s — run scripts/provision_thingsboard.py first", REGISTRY_CSV)
        sys.exit(1)

    rows = list(csv.DictReader(REGISTRY_CSV.open()))
    logger.info("loaded %d devices from registry", len(rows))

    seen_assets = set()
    asset_metadata = []
    for row in rows:
        asset_id = row["room_asset_id"]
        if asset_id in seen_assets:
            continue
        seen_assets.add(asset_id)
        floor_id = int(row["floor_id"])
        attrs = _build_metadata(row["room_key"], floor_id)
        attrs["__asset_id"] = asset_id
        attrs["__room_key"] = row["room_key"]
        asset_metadata.append(attrs)

    client = httpx.Client(timeout=30.0)
    _login(client)
    _rename_campus(client)

    pushed = 0
    for entry in asset_metadata:
        asset_id = entry.pop("__asset_id")
        room_key = entry.pop("__room_key")
        try:
            _post_attrs(client, asset_id, entry)
            pushed += 1
            if pushed % 25 == 0:
                logger.info("  ...%d/%d", pushed, len(asset_metadata))
        except httpx.HTTPStatusError as exc:
            logger.warning("attr push failed for %s: %s", room_key, exc)

    logger.info("done: %d/%d room assets metadata-tagged", pushed, len(asset_metadata))
    client.close()


if __name__ == "__main__":
    main()
