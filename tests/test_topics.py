import unittest

from src.models.room import Room
from src.mqtt.topics import (
    cmd_topic,
    floor_cmd_wildcard,
    floor_summary_topic,
    heartbeat_topic,
    parse_topic,
    response_topic,
    room_base,
    telemetry_topic,
)


class TestTopics(unittest.TestCase):
    def setUp(self):
        self.room = Room("b01", 5, 3)

    def test_room_base(self):
        self.assertEqual(room_base(self.room), "campus/b01/f05/r503")

    def test_telemetry_topic(self):
        self.assertEqual(telemetry_topic(self.room), "campus/b01/f05/r503/telemetry")

    def test_heartbeat_topic(self):
        self.assertEqual(heartbeat_topic(self.room), "campus/b01/f05/r503/heartbeat")

    def test_cmd_topic(self):
        self.assertEqual(cmd_topic(self.room), "campus/b01/f05/r503/cmd")

    def test_response_topic(self):
        self.assertEqual(response_topic(self.room), "campus/b01/f05/r503/response")

    def test_no_legacy_prefix(self):
        # Phase 2 must NOT emit the old bldg_/floor_/room_ form.
        for topic_fn in (telemetry_topic, heartbeat_topic, cmd_topic, response_topic):
            t = topic_fn(self.room)
            self.assertNotIn("bldg_", t)
            self.assertNotIn("floor_", t)
            self.assertNotIn("room_", t)

    def test_floor_summary(self):
        self.assertEqual(floor_summary_topic("b01", 7), "campus/b01/f07/summary")

    def test_floor_cmd_wildcard(self):
        self.assertEqual(floor_cmd_wildcard("b01", 3), "campus/b01/f03/+/cmd")

    def test_room_number_encoding(self):
        # Room number is floor*100 + room_id, zero-padded to 3 digits.
        r1 = Room("b01", 1, 1)
        r10 = Room("b01", 10, 20)
        self.assertEqual(telemetry_topic(r1), "campus/b01/f01/r101/telemetry")
        self.assertEqual(telemetry_topic(r10), "campus/b01/f10/r1020/telemetry")

    def test_parse_roundtrip(self):
        t = telemetry_topic(self.room)
        parsed = parse_topic(t)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["building_id"], "b01")
        self.assertEqual(parsed["floor_id"], 5)
        self.assertEqual(parsed["room_number"], 503)
        self.assertEqual(parsed["leaf"], "telemetry")

    def test_parse_invalid(self):
        self.assertIsNone(parse_topic("foo/bar/baz"))
        self.assertIsNone(parse_topic("campus/b01/floor_05/room_503/telemetry"))


if __name__ == "__main__":
    unittest.main()
