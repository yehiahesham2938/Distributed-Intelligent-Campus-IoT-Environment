import asyncio
import json
import os
import time
import uuid

from gmqtt import Client


_mqtt_client = None
_mqtt_lock = asyncio.Lock()


def _building_suffix(building_id):
    return building_id.replace("b", "")


def _room_number(floor_id, room_id):
    return floor_id * 100 + room_id


def _telemetry_topic(room):
    return (
        f"campus/bldg_{_building_suffix(room.building_id)}/"
        f"floor_{room.floor_id:02d}/room_{_room_number(room.floor_id, room.room_id):03d}/telemetry"
    )


def _heartbeat_topic(room):
    return (
        f"campus/bldg_{_building_suffix(room.building_id)}/"
        f"floor_{room.floor_id:02d}/room_{_room_number(room.floor_id, room.room_id):03d}/heartbeat"
    )


def _telemetry_payload(room):
    return {
        "sensor_id": f"{room.building_id}-f{room.floor_id:02d}-r{_room_number(room.floor_id, room.room_id):03d}",
        "timestamp": int(time.time()),
        "temperature": round(room.temperature, 1),
        "humidity": room.humidity,
        "occupancy": room.occupancy,
        "light_level": room.light,
        "hvac_mode": room.hvac_mode,
    }


async def connect_mqtt():
    global _mqtt_client
    async with _mqtt_lock:
        if _mqtt_client is not None:
            return _mqtt_client

        broker_host = os.getenv("MQTT_BROKER", "localhost")
        broker_port = int(os.getenv("MQTT_PORT", "1883"))
        client_id = os.getenv("MQTT_CLIENT_ID", f"campus-engine-{uuid.uuid4().hex[:8]}")
        username = os.getenv("MQTT_USERNAME")
        password = os.getenv("MQTT_PASSWORD")

        client = Client(client_id)
        if username:
            client.set_auth_credentials(username, password)

        await client.connect(broker_host, broker_port)
        _mqtt_client = client
        return _mqtt_client


async def disconnect_mqtt():
    global _mqtt_client
    async with _mqtt_lock:
        if _mqtt_client is None:
            return

        client = _mqtt_client
        _mqtt_client = None
        await client.disconnect()


async def publish_telemetry(room):
    client = await connect_mqtt()
    topic = _telemetry_topic(room)
    payload = _telemetry_payload(room)
    client.publish(topic, json.dumps(payload), qos=1)


async def publish_heartbeat(room):
    client = await connect_mqtt()
    topic = _heartbeat_topic(room)
    payload = {
        "sensor_id": f"{room.building_id}-f{room.floor_id:02d}-r{_room_number(room.floor_id, room.room_id):03d}",
        "timestamp": int(time.time()),
        "status": "alive",
    }
    client.publish(topic, json.dumps(payload), qos=0)
