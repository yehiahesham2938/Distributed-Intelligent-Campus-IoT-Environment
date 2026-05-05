"""Phase 3 — OTA hash signing + verification + apply tests."""

import unittest

from src.engine.ota import (
    APPLIABLE_PARAMS,
    apply_to_room,
    canonical_hash,
    sign_payload,
    topic_targets_room,
    verify_payload,
)
from src.models.room import Room


class TestCanonicalHash(unittest.TestCase):
    def test_key_order_independence(self):
        a = {"version": "1.0", "params": {"alpha": 0.01, "beta": 0.5}}
        b = {"params": {"beta": 0.5, "alpha": 0.01}, "version": "1.0"}
        self.assertEqual(canonical_hash(a), canonical_hash(b))

    def test_sig_field_excluded(self):
        a = {"version": "1.0", "params": {"alpha": 0.01}}
        b = dict(a, _sig="anything")
        self.assertEqual(canonical_hash(a), canonical_hash(b))

    def test_different_payloads_different_hashes(self):
        a = canonical_hash({"version": "1.0", "params": {"alpha": 0.01}})
        b = canonical_hash({"version": "1.0", "params": {"alpha": 0.02}})
        self.assertNotEqual(a, b)


class TestSignVerify(unittest.TestCase):
    def test_sign_then_verify_passes(self):
        signed = sign_payload({"version": "1.0", "params": {"alpha": 0.01}})
        self.assertIn("_sig", signed)
        ok, _ = verify_payload(signed)
        self.assertTrue(ok)

    def test_tampered_payload_fails(self):
        signed = sign_payload({"version": "1.0", "params": {"alpha": 0.01}})
        signed["params"]["alpha"] = 0.99
        ok, reason = verify_payload(signed)
        self.assertFalse(ok)
        self.assertIn("hash mismatch", reason)

    def test_missing_sig_fails(self):
        ok, _ = verify_payload({"version": "1.0", "params": {"alpha": 0.01}})
        self.assertFalse(ok)

    def test_missing_version_fails(self):
        signed = sign_payload({"params": {"alpha": 0.01}})
        ok, _ = verify_payload(signed)
        self.assertFalse(ok)


class TestTopicTargeting(unittest.TestCase):
    def setUp(self):
        self.room = Room("b01", floor_id=3, room_id=15)

    def test_broadcast_matches(self):
        self.assertTrue(topic_targets_room("campus/b01/ota/config", self.room))

    def test_floor_matches(self):
        self.assertTrue(topic_targets_room("campus/b01/f03/ota", self.room))

    def test_floor_mismatch(self):
        self.assertFalse(topic_targets_room("campus/b01/f04/ota", self.room))

    def test_specific_room_matches(self):
        self.assertTrue(topic_targets_room("campus/b01/f03/r315/ota", self.room))

    def test_specific_room_mismatch(self):
        self.assertFalse(topic_targets_room("campus/b01/f03/r316/ota", self.room))

    def test_other_building_rejected(self):
        self.assertFalse(topic_targets_room("campus/b02/ota/config", self.room))


class TestApplyToRoom(unittest.TestCase):
    def setUp(self):
        self.room = Room("b01", floor_id=1, room_id=1)

    def test_apply_legit_payload(self):
        signed = sign_payload({"version": "2.0", "params": {"alpha": 0.02, "beta": 0.6}})
        result = apply_to_room(self.room, signed, topic="test")
        self.assertFalse(result["rejected"])
        self.assertAlmostEqual(self.room.alpha, 0.02)
        self.assertAlmostEqual(self.room.beta, 0.6)
        self.assertEqual(self.room.config_version, "2.0")

    def test_tampered_rejected(self):
        original_alpha = self.room.alpha
        signed = sign_payload({"version": "9.9", "params": {"alpha": 0.99}})
        signed["params"]["alpha"] = 1.0  # tamper
        result = apply_to_room(self.room, signed, topic="test")
        self.assertTrue(result["rejected"])
        self.assertEqual(self.room.alpha, original_alpha)
        self.assertEqual(self.room.config_version, "1.0")  # unchanged

    def test_unknown_param_skipped_safely(self):
        signed = sign_payload({"version": "3.0", "params": {"alpha": 0.05, "evil_param": "drop_table"}})
        result = apply_to_room(self.room, signed, topic="test")
        self.assertFalse(result["rejected"])
        self.assertIn("evil_param", result["skipped"])
        self.assertAlmostEqual(self.room.alpha, 0.05)

    def test_appliable_params_set_is_documented(self):
        # Sanity: documented whitelist is non-empty and includes core physics.
        self.assertIn("alpha", APPLIABLE_PARAMS)
        self.assertIn("beta", APPLIABLE_PARAMS)


if __name__ == "__main__":
    unittest.main()
