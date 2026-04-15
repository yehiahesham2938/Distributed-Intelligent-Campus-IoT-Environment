"""CoAP node wrapper: boots a CoapNode and drives the physics loop.

Each physics tick calls node.telemetry.notify() which forwards an
Observe notification (RFC 7641) to every gateway subscribed to the
room's telemetry resource. No MQTT involvement here — the gateway's
Node-RED flow is the CoAP-to-MQTT bridge.

Shadow mode: when COAP_MQTT_SHADOW=1 the wrapper also keeps a
lightweight MQTT client attached to HiveMQ so CoAP telemetry lands on
the same `campus/b01/fNN/rRRR/telemetry` topics the MQTT rooms use.
This is the path the Node-RED gateways normally own, but until the
real CoAP-request nodes are dropped into the flow templates the
shadow keeps the cloud side (HiveMQ + ThingsBoard bridge) unified.
"""

import asyncio
import json
import logging
import os
import random
import time

from ..coap.node import CoapNode
from ..engine.physics_loop import physics_loop
from ..mqtt.publisher import MqttNodeClient, broker_host, broker_port
from ..security import credentials as creds_loader
from ..security import psk_store
from ..security import tls

logger = logging.getLogger("nodes.coap_node")


def _shadow_enabled():
    return os.getenv("COAP_MQTT_SHADOW", "0") == "1"


async def run_coap_node(room):
    max_jitter = float(os.getenv("STARTUP_JITTER", "20"))
    await asyncio.sleep(random.uniform(0, max_jitter))

    psk_store.for_room(room)

    node = CoapNode(room)
    try:
        await node.start()
    except Exception as exc:
        logger.error("CoAP node %s failed to bind: %s", room.room_key, exc)
        return

    shadow = None
    if _shadow_enabled():
        try:
            creds = creds_loader.for_room(room)
            tls_ctx = tls.client_context()
            shadow = MqttNodeClient(room, creds, tls_context=tls_ctx)
            # Tag the shadow client_id so HiveMQ metrics distinguish it.
            shadow.client_id = f"coap-shadow-{room.room_key}"
            await shadow.start(broker_host(), broker_port())
            logger.info("CoAP shadow MQTT client up for %s", room.room_key)
        except Exception as exc:
            logger.warning("CoAP shadow failed for %s: %s", room.room_key, exc)
            shadow = None

    async def on_publish(_room):
        try:
            node.telemetry.notify()
        except Exception as exc:
            logger.warning("notify failed for %s: %s", room.room_key, exc)
        if shadow is not None:
            try:
                shadow.publish_telemetry()
                shadow.publish_heartbeat()
            except Exception as exc:
                logger.warning("shadow publish failed for %s: %s", room.room_key, exc)

    try:
        await physics_loop(room, on_publish)
    finally:
        if shadow is not None:
            await shadow.stop()
        await node.stop()
