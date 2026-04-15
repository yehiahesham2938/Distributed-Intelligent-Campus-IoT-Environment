"""Shared per-room physics loop.

Extracted from runtime.run_room so both MQTT and CoAP node wrappers can
drive the same thermal model while owning their own transport-layer
publish semantics. The on_publish callback is invoked each iteration
after faults and persistence; the node wrapper decides how to emit the
new state (MQTT publish, CoAP observe notify, etc.).
"""

import asyncio
import datetime
import logging
import math
import os
import random
import time

from ..persistence import persist_room_state

logger = logging.getLogger("engine.physics_loop")

_sim_start_real = None
_sim_start_virtual = None


def get_virtual_time():
    time_accel = float(os.getenv("TIME_ACCELERATION", "1"))
    global _sim_start_real, _sim_start_virtual
    if _sim_start_real is None:
        _sim_start_real = time.time()
        _sim_start_virtual = datetime.datetime.now()
    elapsed_real = time.time() - _sim_start_real
    elapsed_virtual = elapsed_real * time_accel
    return _sim_start_virtual + datetime.timedelta(seconds=elapsed_virtual)


def get_outside_temperature(hour):
    base_temp = float(os.getenv("OUTSIDE_TEMP", "30"))
    amplitude = float(os.getenv("OUTSIDE_TEMP_AMPLITUDE", "5"))
    return base_temp + amplitude * math.sin(math.pi * (hour - 8) / 12)


def get_outside_humidity(hour):
    base_humidity = float(os.getenv("OUTSIDE_HUMIDITY", "60"))
    amplitude = float(os.getenv("OUTSIDE_HUMIDITY_AMPLITUDE", "10"))
    return base_humidity - amplitude * math.sin(math.pi * (hour - 8) / 12)


async def physics_loop(room, on_publish):
    """Run the Phase 1 physics tick loop for one room forever.

    on_publish: `async def on_publish(room)` — invoked each cycle unless
    the node is in a simulated dropout window. The callback is responsible
    for all transport-layer I/O (MQTT publish, CoAP observe notify, etc.).
    """
    publish_interval = float(os.getenv("PUBLISH_INTERVAL", "5"))
    persist_interval_seconds = int(os.getenv("SQLITE_SAVE_INTERVAL_SECONDS", "30"))
    last_persist_time = 0

    while True:
        start = time.time()

        virtual_now = get_virtual_time()
        current_hour = virtual_now.hour + virtual_now.minute / 60.0
        outside_temp = get_outside_temperature(current_hour)
        outside_humidity = get_outside_humidity(current_hour)

        room.update_occupancy(current_hour)
        room.update_hvac()
        room.update_temperature(outside_temp)
        room.update_light(current_hour)
        room.update_humidity(outside_humidity)
        now = time.time()
        room.apply_sensor_faults(now=now)
        room.validate_state()
        room.last_update = now

        telemetry_faults = room.get_telemetry_faults(now=now)

        if now - last_persist_time >= persist_interval_seconds:
            await asyncio.to_thread(persist_room_state, room)
            last_persist_time = now

        if not telemetry_faults["dropout"]:
            if telemetry_faults["delay_seconds"] > 0:
                await asyncio.sleep(telemetry_faults["delay_seconds"])
            try:
                await on_publish(room)
            except Exception as exc:
                logger.exception("on_publish failed for %s: %s", room.room_key, exc)

        processing_time = time.time() - start
        await asyncio.sleep(max(0, publish_interval - processing_time))
