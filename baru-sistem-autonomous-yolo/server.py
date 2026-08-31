"""HTTP dan WebSocket, kompatibel dengan endpoint yang dibaca web client ZIP."""

import asyncio
import http.server
import json
import threading
from urllib.parse import urlparse

import websockets


def start_http(host: str, port: int, photo_dir, store) -> None:
    class Handler(http.server.BaseHTTPRequestHandler):
        def _json(self, body, code=200):
            payload = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _photo(self, name):
            photo = photo_dir / name
            if not photo.exists():
                return self._json({"error": "photo unavailable"}, 404)
            data = photo.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/health":
                self._json({"ok": True, "service": "sistem-autonomous-waypoint"})
            elif path == "/state":
                self._json(store.snapshot())
            elif path == "/status":
                # Bentuk ini sengaja sama dengan yang diharapkan dashboard.js ZIP.
                self._json({"atas": (photo_dir / "atas.jpg").is_file(), "bawah": (photo_dir / "bawah.jpg").is_file()})
            elif path == "/atas.jpg":
                self._photo("atas.jpg")
            elif path == "/bawah.jpg":
                self._photo("bawah.jpg")
            else:
                self._json({"error": "not found"}, 404)

        def log_message(self, fmt, *args):
            print("[HTTP] " + fmt % args)

    server = http.server.ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="http").start()
    print(f"[HTTP] http://{host}:{port}")


def start_websocket(host: str, port: int, hz: float, store, command_handler=None) -> None:
    async def client(websocket):
        async def tx():
            while True:
                await websocket.send(json.dumps(store.snapshot(), separators=(",", ":")))
                await asyncio.sleep(1 / max(1.0, hz))
        
        async def rx():
            async for raw in websocket:
                try:
                    cmd = json.loads(raw)
                    if not isinstance(cmd, dict) or not isinstance(cmd.get("command"), str):
                        raise ValueError("invalid command")
                    
                    store.command(cmd)
                    
                    result = None
                    if command_handler:
                        result = await asyncio.to_thread(command_handler, cmd)
                        
                    await websocket.send(json.dumps({"type": "ack", "id": cmd.get("id"), "ok": True, "result": result}))
                except Exception as exc:
                    await websocket.send(json.dumps({"type": "ack", "ok": False, "error": str(exc)}))
                    
        tasks = {asyncio.create_task(tx()), asyncio.create_task(rx())}
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*done, return_exceptions=True)

    async def run():
        async with websockets.serve(client, host, port, ping_interval=20, ping_timeout=20, max_size=1_000_000):
            print(f"[WS] ws://{host}:{port}")
            await asyncio.Future()

    threading.Thread(target=lambda: asyncio.run(run()), daemon=True, name="websocket").start()
