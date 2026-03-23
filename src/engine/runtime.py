import asyncio
import time

from .fleet import rooms
from ..mqtt import connect_mqtt, disconnect_mqtt, publish_heartbeat, publish_telemetry


async def run_room(room):
    while True:
        start = time.time()

        room.update_temperature(outside_temp=30)

        await publish_telemetry(room)
        await publish_heartbeat(room)

        processing_time = time.time() - start
        await asyncio.sleep(max(0, 5 - processing_time))


async def main():
    await connect_mqtt()
    try:
        tasks = [run_room(room) for room in rooms]
        await asyncio.gather(*tasks)
    finally:
        await disconnect_mqtt()
