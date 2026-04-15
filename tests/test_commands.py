import unittest

from src.engine.commands import apply_command, parse_payload
from src.models.room import Room


class TestParsePayload(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(parse_payload(b'{"a":1}'), {"a": 1})

    def test_str(self):
        self.assertEqual(parse_payload('{"a":1}'), {"a": 1})

    def test_malformed(self):
        self.assertIsNone(parse_payload(b"not json"))

    def test_non_object(self):
        self.assertIsNone(parse_payload(b"[1,2,3]"))


class TestApplyCommand(unittest.TestCase):
    def setUp(self):
        self.room = Room("b01", 1, 1)
        self.room.temperature = 22.0
        self.room.target_temp = 22.0

    def test_hvac_mode_direct(self):
        applied = apply_command(self.room, {"hvac_mode": "COOLING"})
        self.assertEqual(self.room.hvac_mode, "COOLING")
        self.assertEqual(applied["hvac_mode"], "COOLING")

    def test_hvac_on_translates_to_heating_if_below_target(self):
        self.room.temperature = 18.0
        apply_command(self.room, {"hvac_mode": "ON"})
        self.assertEqual(self.room.hvac_mode, "HEATING")

    def test_hvac_on_translates_to_cooling_if_above_target(self):
        self.room.temperature = 26.0
        apply_command(self.room, {"hvac_mode": "ON"})
        self.assertEqual(self.room.hvac_mode, "COOLING")

    def test_invalid_hvac_mode_ignored(self):
        self.room.hvac_mode = "OFF"
        applied = apply_command(self.room, {"hvac_mode": "BOGUS"})
        self.assertEqual(self.room.hvac_mode, "OFF")
        self.assertNotIn("hvac_mode", applied)

    def test_target_temp_clamped(self):
        apply_command(self.room, {"target_temp": 100})  # out of range
        self.assertEqual(self.room.target_temp, 22.0)  # unchanged
        apply_command(self.room, {"target_temp": 24.0})
        self.assertEqual(self.room.target_temp, 24.0)

    def test_lighting_dimmer_validated(self):
        apply_command(self.room, {"lighting_dimmer": 50})
        self.assertEqual(self.room.lighting_dimmer, 50)
        apply_command(self.room, {"lighting_dimmer": 200})
        self.assertEqual(self.room.lighting_dimmer, 50)  # out of range, unchanged

    def test_applied_dict_tracks_only_changes(self):
        applied = apply_command(
            self.room, {"hvac_mode": "ECO", "target_temp": 24.5, "lighting_dimmer": 10}
        )
        self.assertEqual(applied["hvac_mode"], "ECO")
        self.assertEqual(applied["target_temp"], 24.5)
        self.assertEqual(applied["lighting_dimmer"], 10)


if __name__ == "__main__":
    unittest.main()
