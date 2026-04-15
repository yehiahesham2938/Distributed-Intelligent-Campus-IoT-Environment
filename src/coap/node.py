"""CoapNode — one aiocoap.Context per Room.

Binds to UDP port BASE_COAP_PORT + floor*100 + room_id so each of the 100
CoAP rooms is individually addressable from the floor gateway. With the
default BASE_COAP_PORT=5683 the ports used are 5684..6583, all on 0.0.0.0
so gateway containers can reach them via the compose DNS name `app`.

DTLS-PSK is attached through aiocoap.credentials.CredentialsMap when a
non-empty PSK is available for the room and COAP_DTLS_ENABLED=1.
"""

import logging
import os

import aiocoap
import aiocoap.resource as resource

from ..security import psk_store
from .resources import HvacResource, TelemetryResource

logger = logging.getLogger("coap.node")


def _dtls_enabled():
    return os.getenv("COAP_DTLS_ENABLED", "0") == "1"


def _base_port():
    return int(os.getenv("COAP_BASE_PORT", "5683"))


def port_for(room):
    return _base_port() + room.floor_id * 100 + room.room_id


class CoapNode:
    def __init__(self, room):
        self.room = room
        self.port = port_for(room)
        self.telemetry = TelemetryResource(room)
        self.hvac = HvacResource(room, telemetry_resource=self.telemetry)
        self.site = resource.Site()
        self.site.add_resource(
            [f"f{room.floor_id:02d}", f"r{room.floor_id * 100 + room.room_id:03d}", "telemetry"],
            self.telemetry,
        )
        self.site.add_resource(
            [
                f"f{room.floor_id:02d}",
                f"r{room.floor_id * 100 + room.room_id:03d}",
                "actuators",
                "hvac",
            ],
            self.hvac,
        )
        self.context = None

    async def start(self):
        bind = (os.getenv("COAP_BIND_HOST", "0.0.0.0"), self.port)
        if _dtls_enabled():
            psk = psk_store.for_room(self.room)
            if psk:
                creds = aiocoap.credentials.CredentialsMap()
                creds.load_from_dict(
                    {
                        f"coaps://*": {
                            "dtls": {
                                "psk": psk.hex(),
                                "client-identity": self.room.room_key,
                            }
                        }
                    }
                )
                self.context = await aiocoap.Context.create_server_context(
                    self.site, bind=bind, server_credentials=creds
                )
                logger.info(
                    "CoAP node %s listening DTLS on port %d", self.room.room_key, self.port
                )
                return
            logger.warning(
                "CoAP node %s has no PSK; falling back to plaintext",
                self.room.room_key,
            )
        self.context = await aiocoap.Context.create_server_context(self.site, bind=bind)
        logger.info("CoAP node %s listening on port %d", self.room.room_key, self.port)

    async def stop(self):
        if self.context is not None:
            await self.context.shutdown()
            self.context = None
