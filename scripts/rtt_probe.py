"""RTT probe for the Phase 2 latency audit.

Drives a closed-loop round-trip latency test against the running fleet:

    1. Connects to HiveMQ on localhost:1883.
    2. For each sample, picks a random MQTT or CoAP room from the fleet.
    3. Subscribes to the room's .../response topic.
    4. Publishes a command to .../cmd at QoS 2 with a fresh cmd_id,
       capturing the monotonic clock at publish time.
    5. Waits for the matching response; measures delta in ms.
    6. Writes (wall_ts, protocol, room_key, rtt_ms) to
       data/rtt_metrics.csv.

Run:  venv/bin/python scripts/rtt_probe.py [--count N]

The script is safe to interrupt with Ctrl-C and restart — each run
appends to the CSV so you can build a larger sample over time.
"""

import argparse
import asyncio
import csv
import json
import os
import random
import time
import uuid
from pathlib import Path

import gmqtt

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "data" / "phase2_registry.csv"
OUT_CSV = ROOT / "data" / "rtt_metrics.csv"

HIVEMQ_HOST = os.getenv("HIVEMQ_HOST", "localhost")
HIVEMQ_PORT = int(os.getenv("HIVEMQ_PORT", "1883"))


def load_rooms():
    rooms = []
    with REGISTRY.open() as f:
        for row in csv.DictReader(f):
            rooms.append((row["room_key"], row["protocol"], int(row["floor_id"])))
    return rooms


def cmd_topic(room_key):
    parts = room_key.split("-")
    building, floor, room = parts[0], parts[1], parts[2]
    return f"campus/{building}/{floor}/{room}/cmd"


def response_topic(room_key):
    parts = room_key.split("-")
    building, floor, room = parts[0], parts[1], parts[2]
    return f"campus/{building}/{floor}/{room}/response"


async def run_probe(count):
    rooms = load_rooms()
    if not rooms:
        print("registry empty — run the provisioner first")
        return

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_header = not OUT_CSV.exists() or OUT_CSV.stat().st_size == 0
    if write_header:
        with OUT_CSV.open("w", newline="") as f:
            f.write("wall_ts,protocol,room_key,rtt_ms\n")

    pending = {}
    results = []

    def on_message(client, topic, payload, qos, props):
        if isinstance(topic, bytes):
            topic = topic.decode()
        try:
            data = json.loads(payload.decode() if isinstance(payload, bytes) else payload)
        except Exception:
            return 0
        cmd_id = data.get("cmd_id")
        if cmd_id and cmd_id in pending:
            entry = pending.pop(cmd_id)
            rtt_ms = (time.monotonic() - entry["issued"]) * 1000.0
            results.append(
                (time.time(), entry["protocol"], entry["room_key"], rtt_ms)
            )
            print(
                f"  rtt {entry['protocol']:4} {entry['room_key']:14} {rtt_ms:7.2f} ms"
            )
        return 0

    client = gmqtt.Client(f"rtt-probe-{uuid.uuid4().hex[:6]}")
    client.on_message = on_message
    await client.connect(HIVEMQ_HOST, HIVEMQ_PORT, keepalive=30)
    client.subscribe("campus/+/+/+/response", qos=1)

    print(f"firing {count} commands at random rooms...")
    for i in range(count):
        room_key, protocol, floor = random.choice(rooms)
        cmd_id = uuid.uuid4().hex
        pending[cmd_id] = {
            "issued": time.monotonic(),
            "room_key": room_key,
            "protocol": protocol,
        }
        payload = {
            "hvac_mode": random.choice(["ECO", "HEATING", "COOLING", "OFF"]),
            "target_temp": round(random.uniform(20.0, 26.0), 1),
            "cmd_id": cmd_id,
        }
        client.publish(cmd_topic(room_key), json.dumps(payload), qos=2)
        await asyncio.sleep(0.15)  # ~6.6 cmd/s

    # Let stragglers come home
    for _ in range(40):
        if not pending:
            break
        await asyncio.sleep(0.25)

    with OUT_CSV.open("a", newline="") as f:
        writer = csv.writer(f)
        for wall_ts, protocol, room_key, rtt_ms in results:
            writer.writerow([f"{wall_ts:.3f}", protocol, room_key, f"{rtt_ms:.2f}"])

    print("")
    print(f"fired  : {count}")
    print(f"got    : {len(results)}")
    print(f"missed : {len(pending)}")
    if results:
        rtts = sorted(r[3] for r in results)
        n = len(rtts)
        print(f"min    : {min(rtts):.2f} ms")
        print(f"median : {rtts[n // 2]:.2f} ms")
        print(f"p95    : {rtts[int(n * 0.95)]:.2f} ms")
        print(f"max    : {max(rtts):.2f} ms")
        by_proto = {}
        for _, p, _, r in results:
            by_proto.setdefault(p, []).append(r)
        for p, rs in by_proto.items():
            print(f"  {p}: n={len(rs)} median={sorted(rs)[len(rs) // 2]:.2f} ms")

    await client.disconnect()
    print(f"\nCSV: {OUT_CSV}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(run_probe(args.count))
