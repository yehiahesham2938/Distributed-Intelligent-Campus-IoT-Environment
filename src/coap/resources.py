"""CoAP resources exposed by each room node.

    /fFF/rRRR/telemetry           — ObservableResource, GET + Observe
    /fFF/rRRR/actuators/hvac      — Resource, PUT (Confirmable)

Both resources bind to one Room instance. The Observable telemetry
resource notifies all registered observers every time the physics loop
finishes a tick, via CoapNode.telemetry.notify() (which defers to
self.updated_state()).
"""

import json
import logging
import time

import aiocoap
import aiocoap.resource as resource

from ..engine.commands import apply_command, build_response, parse_payload
from ..metrics import rtt

logger = logging.getLogger("coap.resources")

CONTENT_FORMAT_JSON = 50


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


class TelemetryResource(resource.ObservableResource):
    def __init__(self, room):
        super().__init__()
        self.room = room

    async def render_get(self, request):
        payload = json.dumps(_telemetry_payload(self.room)).encode()
        return aiocoap.Message(
            code=aiocoap.CONTENT,
            payload=payload,
            content_format=CONTENT_FORMAT_JSON,
        )

    def notify(self):
        # Tell aiocoap to push an update to all current observers.
        self.updated_state()


class HvacResource(resource.Resource):
    """PUT-only actuator resource.

    aiocoap automatically deduplicates CON retransmits via
    (remote, message_id) inside EXCHANGE_LIFETIME, so apply_command runs
    exactly once per logical request even under UDP retransmits.
    """

    def __init__(self, room, telemetry_resource=None):
        super().__init__()
        self.room = room
        self.telemetry_resource = telemetry_resource

    async def render_put(self, request):
        data = parse_payload(request.payload)
        if data is None:
            return aiocoap.Message(
                code=aiocoap.BAD_REQUEST,
                payload=b'{"error":"malformed"}',
                content_format=CONTENT_FORMAT_JSON,
            )

        cmd_id = data.get("cmd_id")
        applied = apply_command(self.room, data)
        if cmd_id is not None:
            rtt.record_cmd_applied(cmd_id)

        # Trigger an observe notification so northbound clients see the
        # new state immediately instead of on the next physics tick.
        if self.telemetry_resource is not None:
            try:
                self.telemetry_resource.notify()
            except Exception as exc:
                logger.warning("notify failed after PUT on %s: %s", self.room.room_key, exc)

        response = build_response(self.room, cmd_id, applied)
        return aiocoap.Message(
            code=aiocoap.CHANGED,
            payload=json.dumps(response).encode(),
            content_format=CONTENT_FORMAT_JSON,
        )
