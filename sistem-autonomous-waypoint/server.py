"""HTTP untuk command dan WebSocket untuk seluruh state dashboard."""

import asyncio
import http.server
import json
import threading
from urllib.parse import urlparse

import websockets


def start_http(host: str, port: int, store, command_handler=None) -> None:
    class Handler(http.server.BaseHTTPRequestHandler):
        def _json(self, body, code=200):
            payload = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/health":
                self._json({"ok": True, "service": "sistem-autonomous-waypoint"})
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            if urlparse(self.path).path != "/api/command":
                return self._json({"error": "not found"}, 404)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > 64 * 1024:
                    raise ValueError("ukuran JSON tidak valid")
                command = json.loads(self.rfile.read(size))
                if not isinstance(command, dict) or not isinstance(command.get("command"), str):
                    raise ValueError("command tidak valid")
                store.command(command)
                result = command_handler(command) if command_handler else None
                self._json({"ok": True, "result": result})
            except (ValueError, json.JSONDecodeError) as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
            except Exception as exc:
                self._json({"ok": False, "error": str(exc)}, 500)

        def log_message(self, fmt, *args):
            print("[HTTP] " + fmt % args)

    server = http.server.ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="http").start()
    print(f"[HTTP] http://{host}:{port}")


def start_websocket(host: str, port: int, hz: float, store) -> None:
    async def client(websocket):
        while True:
            await websocket.send(json.dumps(store.snapshot(), separators=(",", ":")))
            await asyncio.sleep(1 / max(1.0, hz))

    async def run():
        async with websockets.serve(client, host, port, ping_interval=20, ping_timeout=20):
            print(f"[WS] ws://{host}:{port}")
            await asyncio.Future()

    threading.Thread(target=lambda: asyncio.run(run()), daemon=True, name="websocket").start()
