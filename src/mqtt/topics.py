"""Phase 2 short-form topic helpers.

Single source of truth for the `campus/b01/fNN/rRRR/...` hierarchy used by
both MQTT nodes and Node-RED gateways. All topic strings in the system must
flow through these helpers — never hand-format topics elsewhere.
"""


def _floor_segment(floor_id):
    return f"f{floor_id:02d}"


def _room_segment(floor_id, room_id):
    return f"r{floor_id * 100 + room_id:03d}"


def room_base(room):
    return (
        f"campus/{room.building_id}/"
        f"{_floor_segment(room.floor_id)}/"
        f"{_room_segment(room.floor_id, room.room_id)}"
    )


def telemetry_topic(room):
    return f"{room_base(room)}/telemetry"


def heartbeat_topic(room):
    return f"{room_base(room)}/heartbeat"


def cmd_topic(room):
    return f"{room_base(room)}/cmd"


def response_topic(room):
    return f"{room_base(room)}/response"


def floor_summary_topic(building_id, floor_id):
    return f"campus/{building_id}/{_floor_segment(floor_id)}/summary"


def floor_cmd_wildcard(building_id, floor_id):
    return f"campus/{building_id}/{_floor_segment(floor_id)}/+/cmd"


def parse_topic(topic):
    """Parse a campus topic back into its components.

    Returns a dict with building_id, floor_id, room_number, leaf — or None
    if the topic does not match the expected hierarchy.
    """
    parts = topic.split("/")
    if len(parts) != 5 or parts[0] != "campus":
        return None
    building_id = parts[1]
    floor_part = parts[2]
    room_part = parts[3]
    leaf = parts[4]
    if not floor_part.startswith("f") or not room_part.startswith("r"):
        return None
    try:
        floor_id = int(floor_part[1:])
        room_number = int(room_part[1:])
    except ValueError:
        return None
    return {
        "building_id": building_id,
        "floor_id": floor_id,
        "room_number": room_number,
        "leaf": leaf,
    }
