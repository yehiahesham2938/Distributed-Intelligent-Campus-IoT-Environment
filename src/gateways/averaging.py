"""Edge-thinning helper used by the Node-RED floor gateways.

The gateway maintains a 60-second rolling window of telemetry samples
per room on its floor and publishes a single floor summary to HiveMQ.
This module is the reference Python implementation that backs
tests/test_edge_thinning.py. The equivalent logic is ported inline in
the Node-RED function node, but unit-testing the Python keeps the math
verifiable in CI.
"""

import time
from collections import deque


class FloorAverager:
    def __init__(self, window_seconds=60, now_fn=None):
        self.window_seconds = window_seconds
        self._samples = deque()
        self._now = now_fn or time.time

    def add_sample(self, room_key, temperature, humidity, occupancy):
        ts = self._now()
        self._samples.append(
            {
                "ts": ts,
                "room_key": room_key,
                "temperature": float(temperature),
                "humidity": float(humidity),
                "occupancy": 1 if occupancy else 0,
            }
        )
        self._evict(ts)

    def _evict(self, now):
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0]["ts"] < cutoff:
            self._samples.popleft()

    def summary(self):
        now = self._now()
        self._evict(now)
        if not self._samples:
            return None
        n = len(self._samples)
        avg_temp = sum(s["temperature"] for s in self._samples) / n
        avg_hum = sum(s["humidity"] for s in self._samples) / n
        occupied_ratio = sum(s["occupancy"] for s in self._samples) / n
        rooms_seen = len({s["room_key"] for s in self._samples})
        return {
            "window_seconds": self.window_seconds,
            "samples": n,
            "rooms_seen": rooms_seen,
            "avg_temperature": round(avg_temp, 2),
            "avg_humidity": round(avg_hum, 2),
            "occupied_ratio": round(occupied_ratio, 3),
            "generated_at": int(now),
        }
