"""Demo client: connects to the websocket service, subscribes to symbols, and prints incoming messages."""
import asyncio
import json
import websockets


async def run(uri: str, symbols: list[str]):
    async with websockets.connect(uri) as ws:
        # subscribe to each symbol
        for s in symbols:
            await ws.send(json.dumps({"action": "subscribe", "topic": f"symbol:{s}"}))
        print(f"Subscribed to: {symbols}")
        try:
            while True:
                msg = await ws.recv()
                try:
                    data = json.loads(msg)
                except Exception:
                    data = msg
                print("RECV:", json.dumps(data, indent=2, default=str))
        except asyncio.CancelledError:
            return
        except Exception as exc:
            print("Client error:", exc)


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://localhost:8001/ws/notifications")
    p.add_argument("--symbols", nargs="*", default=["TD.TO"])
    args = p.parse_args()
    asyncio.run(run(args.url, args.symbols))


if __name__ == "__main__":
    main()
