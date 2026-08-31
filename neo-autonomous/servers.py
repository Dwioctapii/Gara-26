"""HTTP status, WebSocket telemetry, dan WebSocket input YOLO."""

from __future__ import annotations

import asyncio
import http.server
import json
import threading
from urllib.parse import urlparse

import websockets


def start_http(host: str, port: int, store) -> None:
    class Handler(http.server.BaseHTTPRequestHandler):
        def _json(self, body, code=200):
            payload = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/health":
                self._json({"ok": True, "service": "neo-autonomous"})
            elif path in {"/state", "/status"}:
                self._json(store.snapshot())
            else:
                self._json({"error": "not found"}, 404)

        def log_message(self, fmt, *args):
            print("[HTTP] " + fmt % args)

    server = http.server.ThreadingHTTPServer((host, port), Handler)
    threading.Thread(
        target=server.serve_forever,
        daemon=True,
        name="http",
    ).start()
    print(f"[HTTP] http://{host}:{port}")


def start_telemetry_websocket(
    host: str,
    port: int,
    hz: float,
    store,
    command_handler,
) -> None:
    async def client(websocket):
        async def transmit():
            while True:
                await websocket.send(
                    json.dumps(store.snapshot(), separators=(",", ":"))
                )
                await asyncio.sleep(1.0 / max(hz, 1.0))

        async def receive():
            async for raw in websocket:
                command_id = None
                try:
                    cmd = json.loads(raw)
                    if not isinstance(cmd, dict) or not isinstance(
                        cmd.get("command"), str
                    ):
                        raise ValueError("invalid command")
                    command_id = cmd.get("id")
                    state_result = store.command(cmd)
                    mavlink_result = await asyncio.to_thread(command_handler, cmd)
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "ack",
                                "id": command_id,
                                "ok": True,
                                "result": {
                                    "state": state_result,
                                    "mavlink": mavlink_result,
                                },
                            }
                        )
                    )
                except Exception as exc:
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "ack",
                                "id": command_id,
                                "ok": False,
                                "error": str(exc),
                            }
                        )
                    )

        tasks = {
            asyncio.create_task(transmit()),
            asyncio.create_task(receive()),
        }
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*done, return_exceptions=True)

    async def run():
        async with websockets.serve(
            client,
            host,
            port,
            ping_interval=20,
            ping_timeout=20,
            max_size=1_000_000,
        ):
            print(f"[WS TELEMETRY] ws://{host}:{port}")
            await asyncio.Future()

    threading.Thread(
        target=lambda: asyncio.run(run()),
        daemon=True,
        name="telemetry-websocket",
    ).start()


def start_target_websocket(host: str, port: int, store) -> None:
    async def client(websocket):
        store.update({"vision": {"connected": True, "last_error": None}})
        try:
            async for raw in websocket:
                try:
                    payload = json.loads(raw)
                    store.ingest_yolo(payload)
                except Exception as exc:
                    store.set_vision_error(str(exc))
                    print(f"[WS TARGET] Payload ditolak: {exc}")
        finally:
            store.update({"vision": {"connected": False}})

    async def run():
        async with websockets.serve(
            client,
            host,
            port,
            ping_interval=10,
            ping_timeout=10,
            max_size=1_000_000,
        ):
            print(f"[WS TARGET] ws://{host}:{port}")
            await asyncio.Future()

    threading.Thread(
        target=lambda: asyncio.run(run()),
        daemon=True,
        name="target-websocket",
    ).start()

