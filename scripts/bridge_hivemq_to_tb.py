"""HiveMQ -> ThingsBoard device telemetry bridge.

ThingsBoard CE doesn't have the fleet-wide MQTT Integration feature
that TB PE has, so we bridge it ourselves in ~60 lines:

    1. Load data/phase2_registry.csv to map room_key -> TB access_token.
    2. Subscribe on HiveMQ (localhost:1883) to campus/#.
    3. For each telemetry/heartbeat/response message, look up the
       device's TB token and republish to v1/devices/me/telemetry on
       TB's MQTT broker (localhost:1884), authenticated as that device.

Run this on the host while the full docker compose stack is up. All
200 devices flip to Active in the TB UI within a few seconds.
"""

import asyncio
import csv
import json
import logging
import os
import sys
from pathlib import Path

import aiocoap
import gmqtt

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_CSV = ROOT / "data" / "phase2_registry.csv"

HIVEMQ_HOST = os.getenv("HIVEMQ_HOST", "localhost")
HIVEMQ_PORT = int(os.getenv("HIVEMQ_PORT", "1883"))
TB_HOST = os.getenv("TB_HOST", "localhost")
TB_MQTT_PORT = int(os.getenv("TB_MQTT_PORT", "1884"))
COAP_HOST = os.getenv("COAP_HOST", "localhost")
COAP_BASE_PORT = int(os.getenv("COAP_BASE_PORT", "5683"))
COAP_POLL_INTERVAL = float(os.getenv("COAP_POLL_INTERVAL", "5"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | bridge | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bridge")


def load_registry():
    """room_key -> (device_name, access_token)"""
    if not REGISTRY_CSV.exists():
        logger.error("registry not found at %s — run provisioner first", REGISTRY_CSV)
        sys.exit(1)
    mapping = {}
    with REGISTRY_CSV.open() as f:
        for row in csv.DictReader(f):
            token = row.get("access_token", "").strip()
            if not token:
                continue
            mapping[row["room_key"]] = (row["device_name"], token)
    logger.info("loaded %d devices with access tokens from registry", len(mapping))
    return mapping


class TBPublisherPool:
    """One gmqtt client per TB device, lazily created on first use.

    TB's MQTT broker authenticates each client with the device's
    access token as the username (empty password). One device = one
    persistent MQTT client. Pool caches them so we don't reconnect.
    """

    def __init__(self, registry):
        self.registry = registry
        self.clients = {}
        self._lock = asyncio.Lock()
        self._connecting = set()

    async def publish(self, room_key, payload):
        entry = self.registry.get(room_key)
        if entry is None:
            return
        device_name, token = entry

        client = self.clients.get(room_key)
        if client is None:
            async with self._lock:
                client = self.clients.get(room_key)
                if client is None:
                    client = gmqtt.Client(f"bridge-{device_name}")
                    client.set_auth_credentials(token, None)
                    try:
                        await client.connect(TB_HOST, TB_MQTT_PORT, keepalive=60)
                    except Exception as exc:
                        logger.warning("TB connect failed for %s: %s", device_name, exc)
                        return
                    self.clients[room_key] = client

        try:
            client.publish("v1/devices/me/telemetry", json.dumps(payload), qos=1)
        except Exception as exc:
            logger.warning("TB publish failed for %s: %s", device_name, exc)

    async def shutdown(self):
        for client in list(self.clients.values()):
            try:
                await client.disconnect()
            except Exception:
                pass


async def main():
    registry = load_registry()
    pool = TBPublisherPool(registry)

    forwarded = {"total": 0, "by_leaf": {}}

    hivemq = gmqtt.Client(f"hivemq-tb-bridge")
    loop = asyncio.get_event_loop()

    def on_connect(c, flags, rc, props):
        logger.info("hivemq connected rc=%s, subscribing to campus/#", rc)
        c.subscribe("campus/#", qos=1)

    def on_message(c, topic, payload, qos, props):
        if isinstance(topic, bytes):
            topic = topic.decode()
        try:
            data = json.loads(payload.decode() if isinstance(payload, bytes) else payload)
        except Exception:
            return 0

        parts = topic.split("/")
        if len(parts) != 5 or parts[0] != "campus":
            return 0
        # campus/b01/fNN/rRRR/{telemetry,heartbeat,response,cmd}
        leaf = parts[4]
        if leaf not in ("telemetry", "heartbeat", "response"):
            return 0

        room_key = data.get("sensor_id")
        if not room_key:
            return 0

        if leaf == "telemetry":
            tb_payload = {
                k: v
                for k, v in data.items()
                if k in ("temperature", "humidity", "occupancy",
                         "light_level", "lighting_dimmer", "hvac_mode", "target_temp")
            }
        elif leaf == "heartbeat":
            tb_payload = {"status": data.get("status", "unknown")}
        else:  # response
            tb_payload = {"last_response": data}

        if not tb_payload:
            return 0

        forwarded["total"] += 1
        forwarded["by_leaf"][leaf] = forwarded["by_leaf"].get(leaf, 0) + 1
        loop.create_task(pool.publish(room_key, tb_payload))
        return 0

    hivemq.on_connect = on_connect
    hivemq.on_message = on_message
    await hivemq.connect(HIVEMQ_HOST, HIVEMQ_PORT, keepalive=60)

    async def report():
        while True:
            await asyncio.sleep(10)
            logger.info(
                "forwarded=%d by_leaf=%s tb_clients=%d",
                forwarded["total"],
                forwarded["by_leaf"],
                len(pool.clients),
            )

    reporter = asyncio.create_task(report())
    try:
        # Run forever until Ctrl-C
        await asyncio.Event().wait()
    finally:
        reporter.cancel()
        await hivemq.disconnect()
        await pool.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("bridge stopped")
