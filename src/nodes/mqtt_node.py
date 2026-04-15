"""MQTT node wrapper: wires an MqttNodeClient into the physics loop."""

import asyncio
import logging
import os
import random

from ..engine.physics_loop import physics_loop
from ..mqtt.publisher import MqttNodeClient, broker_host, broker_port
from ..security import credentials as creds_loader
from ..security import tls

logger = logging.getLogger("nodes.mqtt_node")


async def run_mqtt_node(room):
    """Start one MQTT node for the given room and run the physics loop."""
    max_jitter = float(os.getenv("STARTUP_JITTER", "20"))
    await asyncio.sleep(random.uniform(0, max_jitter))

    creds = creds_loader.for_room(room)
    tls_ctx = tls.client_context()
    node = MqttNodeClient(room, creds, tls_context=tls_ctx)

    try:
        await node.start(broker_host(), broker_port())
    except Exception as exc:
        logger.error("MQTT node %s failed to connect: %s", room.room_key, exc)
        return

    async def on_publish(_room):
        node.publish_telemetry()
        node.publish_heartbeat()

    try:
        await physics_loop(room, on_publish)
    finally:
        await node.stop()
