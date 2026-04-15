"""Phase 2 runtime dispatcher.

Boots SQLite, loads prior state, then spawns one task per room according
to room.protocol: MQTT rooms become per-node gmqtt clients, CoAP rooms
become aiocoap Observable servers. A background RTT flusher task writes
latency samples to data/rtt_metrics.csv for the audit report.
"""

import asyncio
import logging

from ..metrics import rtt
from ..nodes.coap_node import run_coap_node
from ..nodes.mqtt_node import run_mqtt_node
from ..persistence import (
    init_db,
    initialize_defaults,
    is_db_empty,
    load_previous_state,
)
from ..security import credentials as creds_loader
from ..security import psk_store
from ..utils.logging_config import setup_logging
from .fleet import rooms

logger = logging.getLogger("engine.runtime")


async def main():
    setup_logging()

    logger.info("Initializing database...")
    await asyncio.to_thread(init_db)
    db_empty = await asyncio.to_thread(is_db_empty)

    if db_empty:
        await asyncio.to_thread(initialize_defaults, rooms)
        logger.info("Initialized defaults for %d rooms", len(rooms))
    else:
        await asyncio.to_thread(load_previous_state, rooms)
        logger.info("Loaded previous state for %d rooms", len(rooms))

    creds_loader.load()
    psk_store.load()

    mqtt_count = sum(1 for r in rooms if r.protocol == "mqtt")
    coap_count = sum(1 for r in rooms if r.protocol == "coap")
    logger.info(
        "Starting dispatcher: %d MQTT nodes, %d CoAP nodes (%d total)",
        mqtt_count,
        coap_count,
        len(rooms),
    )

    tasks = []
    for room in rooms:
        if room.protocol == "mqtt":
            tasks.append(asyncio.create_task(run_mqtt_node(room), name=f"mqtt-{room.room_key}"))
        else:
            tasks.append(asyncio.create_task(run_coap_node(room), name=f"coap-{room.room_key}"))

    tasks.append(asyncio.create_task(rtt.flusher(), name="rtt-flusher"))

    try:
        await asyncio.gather(*tasks)
    finally:
        logger.info("Runtime shutting down")
