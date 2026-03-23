import json
import time


async def publish_telemetry(room):
    payload = {
        "timestamp": time.time(),
        "building_id": room.building_id,
        "floor_id": room.floor_id,
        "room_id": room.room_id,
        "temperature": room.temperature,
        "humidity": room.humidity,
        "occupancy": room.occupancy,
        "light": room.light,
    }
    _ = json.dumps(payload)


async def publish_heartbeat(room):
    payload = {
        "timestamp": time.time(),
        "building_id": room.building_id,
        "floor_id": room.floor_id,
        "room_id": room.room_id,
        "status": "alive",
    }
    _ = json.dumps(payload)
