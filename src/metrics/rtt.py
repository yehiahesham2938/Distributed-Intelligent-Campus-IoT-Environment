"""Round-trip-time instrumentation for Phase 2 command latency audits.

The engine's nodes do not originate commands; ThingsBoard does. But for
the latency benchmark we need a closed-loop measurement that starts and
ends in the same process. The flow:

    1. A probe task (or external tester) calls record_cmd_issued(cmd_id,
       room_key) BEFORE publishing the command via HTTP/MQTT.
    2. The node's on_message / CoAP render_put calls
       record_cmd_applied(cmd_id) after apply_command succeeds.
    3. The flusher() task drains the CSV queue every 5 seconds into
       data/rtt_metrics.csv for the report generator to consume.

Use time.monotonic() for the delta so wall-clock drift doesn't skew it.
"""

import asyncio
import logging
import os
import time

logger = logging.getLogger("metrics.rtt")

_pending = {}
_queue = None


def _get_queue():
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue


def record_cmd_issued(cmd_id, room_key):
    if cmd_id is None:
        return
    _pending[cmd_id] = {
        "issued_ts": time.monotonic(),
        "room_key": room_key,
    }


def record_cmd_applied(cmd_id):
    if cmd_id is None:
        return
    entry = _pending.pop(cmd_id, None)
    if entry is None:
        return
    rtt_ms = (time.monotonic() - entry["issued_ts"]) * 1000.0
    try:
        _get_queue().put_nowait((time.time(), entry["room_key"], rtt_ms))
    except asyncio.QueueFull:
        logger.warning("RTT queue full — dropping sample")
    logger.info("RTT %s cmd_id=%s rtt=%.1fms", entry["room_key"], cmd_id, rtt_ms)


async def flusher(csv_path=None):
    path = csv_path or os.getenv("RTT_CSV_PATH", "data/rtt_metrics.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    queue = _get_queue()
    # Ensure header
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write("wall_ts,room_key,rtt_ms\n")
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=5.0)
        except asyncio.TimeoutError:
            continue
        batch = [item]
        while not queue.empty():
            batch.append(queue.get_nowait())
        with open(path, "a") as f:
            for wall_ts, room_key, rtt_ms in batch:
                f.write(f"{wall_ts:.3f},{room_key},{rtt_ms:.2f}\n")
