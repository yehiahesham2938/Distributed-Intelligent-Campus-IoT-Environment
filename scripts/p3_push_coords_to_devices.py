"""Phase 3 — push coordinates_x / coordinates_y from Room assets onto
their child Devices as server-scope attributes.

The Image Map widget binds to devices (not assets), so it needs to
read the spatial keys directly off each device. This script copies
each Room asset's coordinates_x/coordinates_y values onto the
corresponding device.

Idempotent: re-running overwrites with the same values.
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
TB_USER = os.getenv("TB_USERNAME", "tenant@thingsboard.org")
TB_PASS = os.getenv("TB_PASSWORD", "tenant")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | p3.coords | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("p3.coords")


def main():
    if not REGISTRY_CSV.exists():
        logger.error("registry not found at %s", REGISTRY_CSV)
        sys.exit(1)

    rows = list(csv.DictReader(REGISTRY_CSV.open()))

    client = httpx.Client(timeout=30.0)
    r = client.post(f"{TB_URL}/api/auth/login",
                    json={"username": TB_USER, "password": TB_PASS})
    r.raise_for_status()
    client.headers["X-Authorization"] = f"Bearer {r.json()['token']}"

    pushed = 0
    failed = 0
    for row in rows:
        device_id = row["device_id"]
        room_asset_id = row["room_asset_id"]

        # Pull coords + room_type off the Room asset
        rr = client.get(
            f"{TB_URL}/api/plugins/telemetry/ASSET/{room_asset_id}/values/attributes/SERVER_SCOPE"
        )
        if rr.status_code != 200:
            failed += 1
            continue
        attrs = {a["key"]: a["value"] for a in rr.json()}

        device_attrs = {
            "coordinates_x": attrs.get("coordinates_x"),
            "coordinates_y": attrs.get("coordinates_y"),
            "room_type": attrs.get("room_type"),
            "square_footage": attrs.get("square_footage"),
            "occupant_capacity": attrs.get("occupant_capacity"),
        }
        device_attrs = {k: v for k, v in device_attrs.items() if v is not None}

        rr = client.post(
            f"{TB_URL}/api/plugins/telemetry/DEVICE/{device_id}/attributes/SERVER_SCOPE",
            json=device_attrs,
        )
        if rr.status_code >= 400:
            failed += 1
            logger.warning("push failed for %s: %s", row["device_name"], rr.text[:120])
        else:
            pushed += 1
            if pushed % 25 == 0:
                logger.info("  ...%d/%d", pushed, len(rows))

    logger.info("done: %d pushed, %d failed", pushed, failed)
    client.close()


if __name__ == "__main__":
    main()
