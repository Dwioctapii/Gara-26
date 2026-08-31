"""CLI kecil untuk mengaktifkan/mematikan Neo melalui WebSocket lokal."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid

import websockets


COMMANDS = {
    "enable": {"command": "autonomy", "action": "enable"},
    "disable": {"command": "autonomy", "action": "disable"},
    "arm": {"command": "arm", "action": "arm"},
    "disarm": {"command": "arm", "action": "disarm"},
    "guided": {"command": "set_mode", "mode": "GUIDED"},
    "manual": {"command": "set_mode", "mode": "MANUAL"},
}


async def send_command(url: str, action: str) -> dict:
    command_id = uuid.uuid4().hex[:8]
    payload = {"id": command_id, **COMMANDS[action]}
    async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
        await ws.send(json.dumps(payload, separators=(",", ":")))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            response = json.loads(raw)
            if response.get("type") == "ack" and response.get("id") == command_id:
                return response


def main() -> int:
    parser = argparse.ArgumentParser(description="Kontrol Neo Autonomous")
    parser.add_argument("action", choices=tuple(COMMANDS))
    parser.add_argument("--url", default="ws://127.0.0.1:8765")
    args = parser.parse_args()

    response = asyncio.run(send_command(args.url, args.action))
    print(json.dumps(response, indent=2))
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
