import argparse
import asyncio
import json
import time
from typing import Optional

from gmqtt import Client


class Sniffer:
    def __init__(self, limit: Optional[int]) -> None:
        self.limit = limit
        self.count = 0
        self.done = asyncio.Event()

    def on_message(self, client, topic, payload, qos, properties):
        if self.done.is_set():
            return 0

        try:
            text = payload.decode("utf-8", errors="ignore")
        except Exception:
            text = str(payload)

        stamp = time.strftime("%H:%M:%S")
        print(f"{stamp} {topic} {text}")
        self.count += 1

        if self.limit is not None and self.count >= self.limit:
            self.done.set()

        return 0


async def main() -> None:
    parser = argparse.ArgumentParser(description="Subscribe to HiveMQ campus topics and print live traffic.")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic", default="campus/#")
    parser.add_argument("--count", type=int, default=0, help="Stop after this many messages (0 = run forever)")
    args = parser.parse_args()

    limit = args.count if args.count > 0 else None
    sniffer = Sniffer(limit=limit)

    client = Client("phase2-sniffer")
    client.on_message = sniffer.on_message

    await client.connect(args.host, args.port)
    client.subscribe(args.topic)

    try:
        if limit is None:
            while True:
                await asyncio.sleep(3600)
        else:
            await sniffer.done.wait()
            await asyncio.sleep(0.1)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
