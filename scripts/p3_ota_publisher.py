"""Phase 3.2 — OTA configuration publisher CLI.

Publishes a signed OTA payload to one of three scopes via HiveMQ:

    --target broadcast            -> campus/<building>/ota/config
    --target floor:NN             -> campus/<building>/fNN/ota
    --target room:b01-fNN-rRRR    -> campus/<building>/fNN/rRRR/ota

The publisher computes a SHA-256 hash over canonical-sorted JSON of the
payload (with `_sig` removed), attaches the hash as `_sig`, and
publishes at QoS 1 retained=False.

Examples:

    # Push new physics constants to the entire fleet, version 1.1
    venv/bin/python scripts/p3_ota_publisher.py \
        --target broadcast --version 1.1 \
        --alpha 0.02 --beta 0.6

    # Push to floor 5 only
    venv/bin/python scripts/p3_ota_publisher.py \
        --target floor:05 --version 2.0 \
        --sensor-drift-rate 0.05

    # Push to a single room with a deliberately tampered payload
    # (for demonstrating tamper detection)
    venv/bin/python scripts/p3_ota_publisher.py \
        --target room:b01-f01-r101 --version 9.9 \
        --alpha 0.99 --corrupt
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import gmqtt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.engine.ota import sign_payload  # noqa: E402

HIVEMQ_HOST = os.getenv("HIVEMQ_HOST", "localhost")
HIVEMQ_PORT = int(os.getenv("HIVEMQ_PORT", "1883"))
BUILDING = os.getenv("BUILDING", "b01")


def topic_for_target(target):
    """target syntax: 'broadcast', 'floor:NN', or 'room:b01-fNN-rRRR'."""
    if target == "broadcast":
        return f"campus/{BUILDING}/ota/config"
    if target.startswith("floor:"):
        floor_part = target.split(":", 1)[1]
        try:
            floor_id = int(floor_part)
        except ValueError:
            sys.exit(f"invalid floor id: {floor_part!r}")
        return f"campus/{BUILDING}/f{floor_id:02d}/ota"
    if target.startswith("room:"):
        room_key = target.split(":", 1)[1]
        # room_key is e.g. b01-f03-r315
        parts = room_key.split("-")
        if len(parts) != 3:
            sys.exit(f"invalid room key: {room_key!r}")
        return f"campus/{parts[0]}/{parts[1]}/{parts[2]}/ota"
    sys.exit(f"unknown target: {target!r}")


def build_payload(args):
    params = {}
    for name, value in (
        ("alpha", args.alpha),
        ("beta", args.beta),
        ("sensor_drift_rate", args.sensor_drift_rate),
        ("frozen_sensor_rate", args.frozen_sensor_rate),
        ("telemetry_delay_rate", args.telemetry_delay_rate),
        ("node_dropout_rate", args.node_dropout_rate),
    ):
        if value is not None:
            params[name] = value
    if not params:
        sys.exit("no parameters supplied — use --alpha, --beta, etc.")

    payload = {"version": args.version, "params": params}
    return payload


async def publish(topic, payload):
    client = gmqtt.Client(f"p3-ota-publisher-{os.getpid()}")
    await client.connect(HIVEMQ_HOST, HIVEMQ_PORT, keepalive=10)
    client.publish(topic, json.dumps(payload), qos=1)
    # Give gmqtt a moment to flush before disconnecting.
    await asyncio.sleep(0.5)
    await client.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Phase 3 OTA publisher")
    parser.add_argument(
        "--target", required=True,
        help="broadcast | floor:NN | room:b01-fNN-rRRR",
    )
    parser.add_argument("--version", required=True, help="config version label, e.g. 1.1")
    parser.add_argument("--alpha", type=float)
    parser.add_argument("--beta", type=float)
    parser.add_argument("--sensor-drift-rate", type=float)
    parser.add_argument("--frozen-sensor-rate", type=float)
    parser.add_argument("--telemetry-delay-rate", type=float)
    parser.add_argument("--node-dropout-rate", type=float)
    parser.add_argument(
        "--corrupt", action="store_true",
        help="tamper with the payload AFTER signing (for demo)",
    )
    args = parser.parse_args()

    topic = topic_for_target(args.target)
    payload = build_payload(args)
    signed = sign_payload(payload)

    if args.corrupt:
        # Bump the alpha by 0.01 after signing — sig will no longer match.
        if "alpha" in signed["params"]:
            signed["params"]["alpha"] += 0.01
        else:
            signed["params"]["__corrupted__"] = True
        print(f"[!] payload tampered AFTER signing — receiver should reject")

    print(f"topic  : {topic}")
    print(f"payload: {json.dumps(signed, indent=2)}")
    asyncio.run(publish(topic, signed))
    print("published.")


if __name__ == "__main__":
    main()
