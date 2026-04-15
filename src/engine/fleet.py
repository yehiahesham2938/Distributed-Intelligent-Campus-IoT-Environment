import os

from ..models import Room


def _protocol_for(room_id, rooms_per_floor):
    """Phase 2 split: rooms 1..N/2 are MQTT, N/2+1..N are CoAP.

    With the default ROOMS_PER_FLOOR=20 and NUM_FLOORS=10 this yields
    100 MQTT + 100 CoAP nodes, and each floor gateway owns 10 of each.
    """
    half = rooms_per_floor // 2
    return "mqtt" if room_id <= half else "coap"


def create_room_fleet():
    num_floors = int(os.getenv("NUM_FLOORS", "10"))
    rooms_per_floor = int(os.getenv("ROOMS_PER_FLOOR", "20"))
    rooms = []

    for floor in range(1, num_floors + 1):
        for room in range(1, rooms_per_floor + 1):
            protocol = _protocol_for(room, rooms_per_floor)
            rooms.append(Room("b01", floor, room, protocol=protocol))

    return rooms


rooms = create_room_fleet()
