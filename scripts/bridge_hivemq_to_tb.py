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
import time
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

    def __init__(self, registry, hivemq_client=None):
        self.registry = registry
        self.clients = {}
        self._lock = asyncio.Lock()
        self._connecting = set()
        # Reverse map of TB-device-name -> room_key, used by attribute
        # subscribers to know who fired a desired-state update.
        self.device_to_room = {k: v[0] for k, v in registry.items()}
        self.hivemq_client = hivemq_client

    def set_hivemq_client(self, client):
        self.hivemq_client = client

    async def _ensure_client(self, room_key):
        entry = self.registry.get(room_key)
        if entry is None:
            return None, None
        device_name, token = entry
        client = self.clients.get(room_key)
        if client is not None:
            return client, device_name

        async with self._lock:
            client = self.clients.get(room_key)
            if client is not None:
                return client, device_name
            client = gmqtt.Client(f"bridge-{device_name}")
            client.set_auth_credentials(token, None)
            # Subscribe to attribute updates so dashboard shared-attribute
            # changes round-trip back to HiveMQ as commands.
            client.on_message = self._make_attr_handler(room_key)
            try:
                await client.connect(TB_HOST, TB_MQTT_PORT, keepalive=60)
                client.subscribe("v1/devices/me/attributes", qos=1)
            except Exception as exc:
                logger.warning("TB connect failed for %s: %s", device_name, exc)
                return None, device_name
            self.clients[room_key] = client
            return client, device_name

    def _make_attr_handler(self, room_key):
        """Return an on_message that converts shared-attribute updates
        into MQTT commands on HiveMQ. TB delivers shared attributes on
        v1/devices/me/attributes as JSON like {"shared":{...}} or
        directly {"key":"value"}.
        """
        def _handler(client, topic, payload, qos, props):
            if not self.hivemq_client:
                return 0
            try:
                data = json.loads(payload.decode() if isinstance(payload, bytes) else payload)
            except Exception:
                return 0
            shared = data.get("shared") if isinstance(data, dict) else None
            if shared is None:
                shared = data if isinstance(data, dict) else {}
            cmd = {}
            if "desired_hvac_mode" in shared:
                cmd["hvac_mode"] = shared["desired_hvac_mode"]
            if "desired_target_temp" in shared:
                try:
                    cmd["target_temp"] = float(shared["desired_target_temp"])
                except (TypeError, ValueError):
                    pass
            if "desired_lighting_dimmer" in shared:
                try:
                    cmd["lighting_dimmer"] = int(shared["desired_lighting_dimmer"])
                except (TypeError, ValueError):
                    pass
            if not cmd:
                return 0
            cmd["cmd_id"] = f"shared-{int(time.time()*1000)}"
            # Build the campus/.../cmd topic from the room_key.
            building, floor, room = room_key.split("-")
            topic_str = f"campus/{building}/{floor}/{room}/cmd"
            self.hivemq_client.publish(topic_str, json.dumps(cmd), qos=2)
            logger.info("desired -> cmd on %s: %s", topic_str, cmd)
            return 0
        return _handler

    async def publish_telemetry(self, room_key, payload):
        client, device_name = await self._ensure_client(room_key)
        if client is None:
            return
        try:
            client.publish("v1/devices/me/telemetry", json.dumps(payload), qos=1)
        except Exception as exc:
            logger.warning("TB tele publish failed for %s: %s", device_name, exc)

    async def publish_attributes(self, room_key, payload):
        client, device_name = await self._ensure_client(room_key)
        if client is None:
            return
        try:
            client.publish("v1/devices/me/attributes", json.dumps(payload), qos=1)
        except Exception as exc:
            logger.warning("TB attr publish failed for %s: %s", device_name, exc)

    # Back-compat shim used by the existing bridge logic below.
    async def publish(self, room_key, payload):
        await self.publish_telemetry(room_key, payload)

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
        if not parts or parts[0] != "campus":
            return 0

        # Phase 3: campus/b01/fNN/rRRR/ota/report  -> reported attributes
        if len(parts) == 6 and parts[4] == "ota" and parts[5] == "report":
            room_key = data.get("sensor_id")
            if not room_key:
                return 0
            attrs = {
                "current_version": str(data.get("version", "?")),
                "ota_rejected": bool(data.get("rejected", False)),
                "ota_reason": data.get("reason", ""),
                "ota_last_topic": data.get("topic", ""),
                "ota_applied": data.get("applied", {}),
                "ota_timestamp": data.get("timestamp"),
            }
            if data.get("rejected"):
                # Tamper alarm marker — TB rule chain can pick this up.
                attrs["security_alert"] = "OTA_TAMPERING"
                attrs["security_alert_at"] = int(time.time())
            forwarded["total"] += 1
            forwarded["by_leaf"]["ota_report"] = forwarded["by_leaf"].get("ota_report", 0) + 1
            loop.create_task(pool.publish_attributes(room_key, attrs))
            return 0

        # Standard 5-segment topics:
        if len(parts) != 5:
            return 0
        # campus/b01/fNN/rRRR/{telemetry,heartbeat,response,cmd}
        leaf = parts[4]
        if leaf not in ("telemetry", "heartbeat", "response"):
            return 0

        room_key = data.get("sensor_id")
        if not room_key:
            return 0

        attr_payload = None  # extra attributes-channel payload, if any

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
            # Phase 3: also publish reported_* as client attributes so the
            # dashboard can compare desired vs reported.
            state = data.get("state", {}) if isinstance(data, dict) else {}
            attr_payload = {
                "reported_hvac_mode": state.get("hvac_mode"),
                "reported_target_temp": state.get("target_temp"),
                "reported_lighting_dimmer": state.get("lighting_dimmer"),
                "last_command_at": data.get("timestamp"),
                "last_cmd_id": data.get("cmd_id"),
            }
            attr_payload = {k: v for k, v in attr_payload.items() if v is not None}

        if not tb_payload and not attr_payload:
            return 0

        forwarded["total"] += 1
        forwarded["by_leaf"][leaf] = forwarded["by_leaf"].get(leaf, 0) + 1
        if tb_payload:
            loop.create_task(pool.publish_telemetry(room_key, tb_payload))
        if attr_payload:
            loop.create_task(pool.publish_attributes(room_key, attr_payload))
        return 0

    hivemq.on_connect = on_connect
    hivemq.on_message = on_message
    await hivemq.connect(HIVEMQ_HOST, HIVEMQ_PORT, keepalive=60)
    pool.set_hivemq_client(hivemq)

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
