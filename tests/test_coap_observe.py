"""End-to-end CoAP ObservableResource test.

Spins up a CoapNode on an ephemeral UDP port (no DTLS) and exercises:

    1. GET /fFF/rRRR/telemetry returns current state.
    2. PUT /fFF/rRRR/actuators/hvac applies commands.
    3. Observe notifications fire when telemetry.notify() is called.

Runs fully in-process via aiocoap's asyncio context. No external broker.
"""

import asyncio
import json
import os
import unittest

import aiocoap

from src.coap.node import CoapNode, port_for
from src.models.room import Room


def _run(coro):
    return asyncio.run(coro)


class TestCoapNode(unittest.TestCase):
    def setUp(self):
        # Override to an ephemeral-ish range far away from the fleet ports.
        os.environ["COAP_BASE_PORT"] = "45000"
        os.environ["COAP_DTLS_ENABLED"] = "0"
        self.room = Room("b01", 6, 12, protocol="coap")

    def tearDown(self):
        os.environ.pop("COAP_BASE_PORT", None)
        os.environ.pop("COAP_DTLS_ENABLED", None)

    def test_get_telemetry(self):
        async def run():
            node = CoapNode(self.room)
            await node.start()
            try:
                client = await aiocoap.Context.create_client_context()
                uri = f"coap://127.0.0.1:{port_for(self.room)}/f06/r612/telemetry"
                request = aiocoap.Message(code=aiocoap.GET, uri=uri)
                response = await client.request(request).response
                payload = json.loads(response.payload)
                self.assertEqual(payload["sensor_id"], self.room.room_key)
                self.assertIn("temperature", payload)
                await client.shutdown()
            finally:
                await node.stop()
        _run(run())

    def test_put_actuator_applies_command(self):
        async def run():
            node = CoapNode(self.room)
            await node.start()
            try:
                client = await aiocoap.Context.create_client_context()
                uri = f"coap://127.0.0.1:{port_for(self.room)}/f06/r612/actuators/hvac"
                body = json.dumps({"hvac_mode": "ECO", "target_temp": 23.0}).encode()
                request = aiocoap.Message(code=aiocoap.PUT, uri=uri, payload=body)
                response = await client.request(request).response
                self.assertEqual(response.code, aiocoap.CHANGED)
                self.assertEqual(self.room.hvac_mode, "ECO")
                self.assertEqual(self.room.target_temp, 23.0)
                body = json.loads(response.payload)
                self.assertEqual(body["applied"]["hvac_mode"], "ECO")
                await client.shutdown()
            finally:
                await node.stop()
        _run(run())

    def test_observe_receives_notifications(self):
        async def run():
            node = CoapNode(self.room)
            await node.start()
            received = []
            try:
                client = await aiocoap.Context.create_client_context()
                uri = f"coap://127.0.0.1:{port_for(self.room)}/f06/r612/telemetry"

                obs_request = aiocoap.Message(code=aiocoap.GET, uri=uri, observe=0)
                request = client.request(obs_request)
                first = await request.response
                received.append(first.payload)

                async def collect():
                    async for msg in request.observation:
                        received.append(msg.payload)
                        if len(received) >= 3:
                            request.observation.cancel()
                            break

                collect_task = asyncio.create_task(collect())
                # Trigger two state-change notifications
                await asyncio.sleep(0.05)
                self.room.temperature = 25.0
                node.telemetry.notify()
                await asyncio.sleep(0.05)
                self.room.temperature = 26.0
                node.telemetry.notify()
                try:
                    await asyncio.wait_for(collect_task, timeout=2.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                self.assertGreaterEqual(len(received), 2)
                await client.shutdown()
            finally:
                await node.stop()
        _run(run())


if __name__ == "__main__":
    unittest.main()
