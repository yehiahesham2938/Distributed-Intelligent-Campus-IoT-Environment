"""MqttNodeClient unit tests — gmqtt client is mocked so no broker runs."""

import json
import unittest
from unittest.mock import MagicMock, patch

from src.models.room import Room
from src.mqtt.topics import cmd_topic, heartbeat_topic, response_topic, telemetry_topic
from src.security.credentials import MqttCredentials


class TestMqttNodeClient(unittest.TestCase):
    def setUp(self):
        self.room = Room("b01", 3, 5)
        self.creds = MqttCredentials(
            room_key=self.room.room_key, username="mqtt-node-b01-f03-r305", password="pw"
        )

    def _make_node(self):
        # Patch the gmqtt Client constructor so no network happens.
        with patch("src.mqtt.publisher.Client") as ClientCls:
            instance = MagicMock()
            ClientCls.return_value = instance
            from src.mqtt.publisher import MqttNodeClient
            node = MqttNodeClient(self.room, self.creds)
            return node, instance, ClientCls

    def test_client_id_format(self):
        node, _, _ = self._make_node()
        self.assertEqual(node.client_id, f"mqtt-{self.room.room_key}")

    def test_auth_credentials_set(self):
        _, instance, _ = self._make_node()
        instance.set_auth_credentials.assert_called_once_with("mqtt-node-b01-f03-r305", "pw")

    def test_lwt_attached(self):
        _, instance, _ = self._make_node()
        # gmqtt exposes set_will_message; our node wraps it with retain=True qos=1 on heartbeat topic
        instance.set_will_message.assert_called_once()
        args, kwargs = instance.set_will_message.call_args
        topic = args[0]
        payload = args[1]
        self.assertEqual(topic, heartbeat_topic(self.room))
        self.assertEqual(kwargs.get("qos"), 1)
        self.assertTrue(kwargs.get("retain"))
        self.assertIn("offline", payload)

    def test_on_connect_subscribes_own_cmd_topic(self):
        node, instance, _ = self._make_node()
        node._on_connect(instance, flags=0, rc=0, properties={})
        # Should subscribe to cmd topic with qos=2
        instance.subscribe.assert_called_with(cmd_topic(self.room), qos=2)
        # Should publish an online retained heartbeat
        publish_calls = instance.publish.call_args_list
        self.assertTrue(any(heartbeat_topic(self.room) == c.args[0] for c in publish_calls))

    def test_on_message_applies_command_and_publishes_response(self):
        node, instance, _ = self._make_node()
        payload = json.dumps({"hvac_mode": "ECO", "target_temp": 24.0, "cmd_id": "abc"}).encode()
        node._on_message(instance, cmd_topic(self.room), payload, qos=2, properties={})
        self.assertEqual(self.room.hvac_mode, "ECO")
        self.assertEqual(self.room.target_temp, 24.0)
        # response published on response_topic
        response_calls = [
            c for c in instance.publish.call_args_list if c.args[0] == response_topic(self.room)
        ]
        self.assertEqual(len(response_calls), 1)
        body = json.loads(response_calls[0].args[1])
        self.assertEqual(body["cmd_id"], "abc")
        self.assertEqual(body["applied"]["hvac_mode"], "ECO")

    def test_dup_suppressed(self):
        node, instance, _ = self._make_node()
        props = {"dup": True, "message_id": 42}
        # First DUP=True with a NEW id will slip through — that's fine because
        # we only treat as duplicate when we've seen the id AND dup is set.
        # Seed the deque with id 42 then retry.
        node._seen_packet_ids.append(42)
        calls_before = len(instance.publish.call_args_list)
        node._on_message(
            instance,
            cmd_topic(self.room),
            json.dumps({"hvac_mode": "COOLING"}).encode(),
            qos=2,
            properties=props,
        )
        calls_after = len(instance.publish.call_args_list)
        # No response published — DUP was suppressed
        self.assertEqual(calls_before, calls_after)

    def test_malformed_payload_is_ignored(self):
        node, instance, _ = self._make_node()
        calls_before = len(instance.publish.call_args_list)
        node._on_message(instance, cmd_topic(self.room), b"not json", qos=2, properties={})
        self.assertEqual(len(instance.publish.call_args_list), calls_before)

    def test_publish_telemetry_uses_correct_topic_and_qos(self):
        node, instance, _ = self._make_node()
        node.publish_telemetry()
        last = instance.publish.call_args
        self.assertEqual(last.args[0], telemetry_topic(self.room))
        self.assertEqual(last.kwargs.get("qos"), 1)
        body = json.loads(last.args[1])
        self.assertEqual(body["sensor_id"], self.room.room_key)


if __name__ == "__main__":
    unittest.main()
