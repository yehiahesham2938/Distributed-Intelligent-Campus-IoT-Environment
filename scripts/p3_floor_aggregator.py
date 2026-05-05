"""Phase 3.1.1 — Floor-level aggregation daemon.

Subscribes to HiveMQ on `campus/+/+/+/telemetry`, accumulates a 60s
rolling window per floor, and posts avg_temperature / avg_humidity /
occupied_count / occupied_ratio to each Floor asset's telemetry via TB
REST every 30 seconds.

This satisfies the Phase 3 rubric's "Relation Mapping for Aggregation"
requirement using the documented "Script transformation" alternative —
TB CE 3.7 doesn't ship the Aggregate node so we compute outside.

Run alongside bridge_hivemq_to_tb.py:

    nohup venv/bin/python scripts/p3_floor_aggregator.py > data/aggregator.log 2>&1 &
"""

import asyncio
import csv
import json
import logging
import os
import statistics
import time
from collections import defaultdict, deque
from pathlib import Path

import gmqtt
import httpx

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_CSV = ROOT / "data" / "phase2_registry.csv"

HIVEMQ_HOST = os.getenv("HIVEMQ_HOST", "localhost")
HIVEMQ_PORT = int(os.getenv("HIVEMQ_PORT", "1883"))
TB_URL = os.getenv("TB_URL", "http://localhost:9090")
TB_USER = os.getenv("TB_USERNAME", "tenant@thingsboard.org")
TB_PASS = os.getenv("TB_PASSWORD", "tenant")

WINDOW_SECONDS = 60
PUBLISH_INTERVAL = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | aggregator | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("aggregator")


def load_floor_assets():
    """Map floor_id (int) -> floor_asset_id from the registry."""
    floors = {}
    if not REGISTRY_CSV.exists():
        return floors
    with REGISTRY_CSV.open() as f:
        for row in csv.DictReader(f):
            floors[int(row["floor_id"])] = row["floor_asset_id"]
    return floors


def login():
    r = httpx.post(
        f"{TB_URL}/api/auth/login",
        json={"username": TB_USER, "password": TB_PASS},
        timeout=10.0,
    )
    r.raise_for_status()
    return r.json()["token"]


class FloorAggregator:
    def __init__(self):
        self.windows = defaultdict(deque)  # floor_id -> deque of (ts, payload)
        self.tb_token = None
        self.tb_token_at = 0

    def add(self, floor_id, payload):
        ts = time.time()
        self.windows[floor_id].append((ts, payload))
        cutoff = ts - WINDOW_SECONDS
        while self.windows[floor_id] and self.windows[floor_id][0][0] < cutoff:
            self.windows[floor_id].popleft()

    def summary_for(self, floor_id):
        items = list(self.windows.get(floor_id, []))
        if not items:
            return None
        temps = [p.get("temperature") for _, p in items if isinstance(p.get("temperature"), (int, float))]
        hums = [p.get("humidity") for _, p in items if isinstance(p.get("humidity"), (int, float))]
        occ = [bool(p.get("occupancy")) for _, p in items]
        rooms = {p.get("sensor_id") for _, p in items if p.get("sensor_id")}
        if not temps:
            return None
        return {
            "avg_temperature": round(statistics.mean(temps), 2),
            "avg_humidity": round(statistics.mean(hums), 2) if hums else None,
            "occupied_count": sum(1 for o in occ if o),
            "occupied_ratio": round(sum(1 for o in occ if o) / len(occ), 3) if occ else 0.0,
            "rooms_sampled": len(rooms),
            "samples": len(items),
        }

    def get_token(self):
        if self.tb_token and time.time() - self.tb_token_at < 3000:
            return self.tb_token
        self.tb_token = login()
        self.tb_token_at = time.time()
        return self.tb_token

    def post_floor_telemetry(self, floor_asset_id, payload):
        token = self.get_token()
        headers = {"X-Authorization": f"Bearer {token}"}
        r = httpx.post(
            f"{TB_URL}/api/plugins/telemetry/ASSET/{floor_asset_id}/timeseries/ANY",
            json=payload,
            headers=headers,
            timeout=10.0,
        )
        if r.status_code >= 400:
            logger.warning("post failed for %s: %s %s", floor_asset_id, r.status_code, r.text[:120])
        return r.status_code


def parse_topic(topic):
    parts = topic.split("/")
    if len(parts) != 5 or parts[0] != "campus":
        return None
    floor_part = parts[2]
    if not floor_part.startswith("f"):
        return None
    try:
        return int(floor_part[1:])
    except ValueError:
        return None


async def main():
    floor_assets = load_floor_assets()
    if not floor_assets:
        logger.error("no floor assets in registry — run scripts/provision_thingsboard.py first")
        return
    logger.info("monitoring %d floors", len(floor_assets))

    agg = FloorAggregator()

    client = gmqtt.Client("p3-floor-aggregator")

    def on_connect(c, flags, rc, props):
        logger.info("hivemq connected rc=%s", rc)
        c.subscribe("campus/+/+/+/telemetry", qos=1)

    def on_message(c, topic, payload, qos, props):
        if isinstance(topic, bytes):
            topic = topic.decode()
        floor_id = parse_topic(topic)
        if floor_id is None:
            return 0
        try:
            data = json.loads(payload.decode() if isinstance(payload, bytes) else payload)
        except Exception:
            return 0
        agg.add(floor_id, data)
        return 0

    client.on_connect = on_connect
    client.on_message = on_message
    await client.connect(HIVEMQ_HOST, HIVEMQ_PORT, keepalive=60)

    cycles = 0
    try:
        while True:
            await asyncio.sleep(PUBLISH_INTERVAL)
            cycles += 1
            posted = 0
            for floor_id, asset_id in sorted(floor_assets.items()):
                summary = agg.summary_for(floor_id)
                if summary is None:
                    continue
                try:
                    agg.post_floor_telemetry(asset_id, summary)
                    posted += 1
                except Exception as exc:
                    logger.warning("floor %d post error: %s", floor_id, exc)
            logger.info(
                "cycle %d: posted %d/%d floor summaries", cycles, posted, len(floor_assets)
            )
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("aggregator stopped")
