"""Per-room MQTT node client.

Phase 2 replaces the Phase 1 shared gmqtt singleton with one
`MqttNodeClient` per MQTT room. Each client:

    * has a unique ClientID `mqtt-<room_key>`
    * authenticates with its own username/password from credentials.csv
    * connects over TLS to HiveMQ (unless MQTT_TLS_ENABLED is off)
    * declares an LWT on its heartbeat topic (retained, QoS 1, payload
      `{"status":"offline"}`) so HiveMQ publishes the offline marker if
      the TCP session dies without a clean DISCONNECT
    * subscribes ONLY to its own cmd topic at QoS 2
    * deduplicates MQTT DUP retransmits via a 256-entry deque of recent
      packet IDs
    * publishes telemetry at QoS 1 and heartbeats retained at QoS 0
"""

import asyncio
import collections
import json
import logging
import os
import time

from gmqtt import Client
from gmqtt.mqtt.constants import MQTTv311

from ..engine.commands import apply_command, build_response, parse_payload
from ..metrics import rtt
from .topics import cmd_topic, heartbeat_topic, response_topic, telemetry_topic

logger = logging.getLogger("mqtt.publisher")


def _telemetry_payload(room):
    return {
        "sensor_id": room.room_key,
        "timestamp": int(time.time()),
        "temperature": round(room.temperature, 1),
        "humidity": room.humidity,
        "occupancy": room.occupancy,
        "light_level": room.light,
        "lighting_dimmer": room.lighting_dimmer,
        "hvac_mode": room.hvac_mode,
        "target_temp": room.target_temp,
    }


def _heartbeat_payload(room, status="online"):
    return {
        "sensor_id": room.room_key,
        "timestamp": int(time.time()),
        "status": status,
    }


class MqttNodeClient:
    """One gmqtt.Client bound to a single Room."""

    def __init__(self, room, credentials, tls_context=None):
        self.room = room
        self.credentials = credentials
        self.tls_context = tls_context
        self.client_id = f"mqtt-{room.room_key}"
        self._connected_event = asyncio.Event()
        self._seen_packet_ids = collections.deque(maxlen=256)

        # gmqtt will_message is attached via constructor kwarg in recent versions.
        self.client = Client(self.client_id, clean_session=False)
        if credentials.username:
            self.client.set_auth_credentials(credentials.username, credentials.password)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        # LWT: offline marker, retained, QoS 1.
        lwt_payload = json.dumps(_heartbeat_payload(room, status="offline"))
        try:
            self.client.set_will_message(
                heartbeat_topic(room), lwt_payload, qos=1, retain=True
            )
        except AttributeError:
            # Older gmqtt exposes Message helper via gmqtt.Message — fall back.
            from gmqtt import Message
            self.client.will_message = Message(
                heartbeat_topic(room), lwt_payload, qos=1, retain=True
            )

    async def start(self, host, port):
        logger.info(
            "MQTT node %s connecting to %s:%d (tls=%s)",
            self.client_id, host, port, bool(self.tls_context),
        )
        await self.client.connect(
            host,
            port,
            ssl=self.tls_context,
            version=MQTTv311,
            keepalive=30,
        )
        await self._connected_event.wait()

    async def stop(self):
        try:
            # Publish a clean offline marker before disconnecting.
            self.client.publish(
                heartbeat_topic(self.room),
                json.dumps(_heartbeat_payload(self.room, status="offline")),
                qos=1,
                retain=True,
            )
            await self.client.disconnect()
        except Exception as exc:
            logger.warning("stop() error for %s: %s", self.client_id, exc)

    def _on_connect(self, client, flags, rc, properties):
        logger.info("MQTT node %s connected rc=%s", self.client_id, rc)
        # Subscribe ONLY to own cmd topic at QoS 2.
        client.subscribe(cmd_topic(self.room), qos=2)
        # Overwrite LWT retained marker with an online state.
        client.publish(
            heartbeat_topic(self.room),
            json.dumps(_heartbeat_payload(self.room, status="online")),
            qos=1,
            retain=True,
        )
        self._connected_event.set()

    def _on_disconnect(self, client, packet, exc=None):
        logger.warning("MQTT node %s disconnected: %s", self.client_id, exc)
        self._connected_event.clear()

    def _on_message(self, client, topic, payload, qos, properties):
        if isinstance(topic, bytes):
            topic = topic.decode()

        dup_flag = False
        packet_id = None
        if isinstance(properties, dict):
            dup_flag = bool(properties.get("dup", False))
            packet_id = properties.get("message_id") or properties.get("packet_id")

        if dup_flag and packet_id is not None and packet_id in self._seen_packet_ids:
            logger.info(
                "DUP suppressed on %s id=%s", self.room.room_key, packet_id
            )
            return 0
        if packet_id is not None:
            self._seen_packet_ids.append(packet_id)

        data = parse_payload(payload)
        if data is None:
            logger.warning("malformed cmd on %s", topic)
            return 0

        cmd_id = data.get("cmd_id")
        applied = apply_command(self.room, data)
        if cmd_id is not None:
            rtt.record_cmd_applied(cmd_id)

        response = build_response(self.room, cmd_id, applied)
        client.publish(response_topic(self.room), json.dumps(response), qos=1)
        return 0

    def publish_telemetry(self):
        self.client.publish(
            telemetry_topic(self.room),
            json.dumps(_telemetry_payload(self.room)),
            qos=1,
        )

    def publish_heartbeat(self):
        self.client.publish(
            heartbeat_topic(self.room),
            json.dumps(_heartbeat_payload(self.room, status="online")),
            qos=0,
            retain=True,
        )


def broker_host():
    return os.getenv("MQTT_BROKER", "localhost")


def broker_port():
    if os.getenv("MQTT_TLS_ENABLED", "0") == "1":
        return int(os.getenv("MQTT_TLS_PORT", "8883"))
    return int(os.getenv("MQTT_PORT", "1883"))
