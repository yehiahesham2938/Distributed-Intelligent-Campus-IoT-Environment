import unittest

from src.gateways.averaging import FloorAverager


class TestFloorAverager(unittest.TestCase):
    def test_empty_window_returns_none(self):
        avg = FloorAverager(window_seconds=60, now_fn=lambda: 1000.0)
        self.assertIsNone(avg.summary())

    def test_basic_average(self):
        t = [1000.0]
        avg = FloorAverager(window_seconds=60, now_fn=lambda: t[0])
        avg.add_sample("b01-f01-r101", 22.0, 50.0, True)
        avg.add_sample("b01-f01-r102", 24.0, 60.0, False)
        s = avg.summary()
        self.assertEqual(s["samples"], 2)
        self.assertEqual(s["rooms_seen"], 2)
        self.assertEqual(s["avg_temperature"], 23.0)
        self.assertEqual(s["avg_humidity"], 55.0)
        self.assertEqual(s["occupied_ratio"], 0.5)

    def test_window_eviction(self):
        now = [1000.0]
        avg = FloorAverager(window_seconds=60, now_fn=lambda: now[0])
        avg.add_sample("b01-f01-r101", 20.0, 40.0, False)
        now[0] = 1030.0
        avg.add_sample("b01-f01-r101", 24.0, 60.0, True)
        # Still within window — both samples present
        s = avg.summary()
        self.assertEqual(s["samples"], 2)
        self.assertEqual(s["avg_temperature"], 22.0)
        # Advance past the window for the first sample
        now[0] = 1061.0
        s = avg.summary()
        self.assertEqual(s["samples"], 1)
        self.assertEqual(s["avg_temperature"], 24.0)

    def test_all_samples_expire(self):
        now = [1000.0]
        avg = FloorAverager(window_seconds=10, now_fn=lambda: now[0])
        avg.add_sample("b01-f01-r101", 22.0, 50.0, True)
        now[0] = 2000.0
        self.assertIsNone(avg.summary())

    def test_occupied_ratio(self):
        now = [1000.0]
        avg = FloorAverager(window_seconds=60, now_fn=lambda: now[0])
        for i in range(4):
            avg.add_sample(f"room{i}", 22.0, 50.0, i < 3)  # 3 occupied, 1 not
        s = avg.summary()
        self.assertEqual(s["samples"], 4)
        self.assertEqual(s["occupied_ratio"], 0.75)


if __name__ == "__main__":
    unittest.main()
