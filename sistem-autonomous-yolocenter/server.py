"""HTTP dan WebSocket, kompatibel dengan endpoint yang dibaca web client ZIP."""

import asyncio
import http.server
import json
import os
import threading
import time
from urllib.parse import urlparse

import websockets


def _encode_live_frame(store, quality: int, previous_sequence: int) -> tuple[bytes | None, int]:
    """Ambil satu frame konsisten dan kompres di worker thread."""
    if hasattr(store, "frame_snapshot"):
        frame, sequence = store.frame_snapshot()
    else:
        frame = getattr(store, "live_frame_bgr", None)
        sequence = id(frame)
    if frame is None:
        return None, sequence
    if sequence == previous_sequence:
        return None, sequence
    try:
        import cv2

        ok, encoded = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        )
        return (encoded.tobytes() if ok else None), sequence
    except Exception:
        return None, sequence


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
        profile = {
            "state": True,
            "camera": False,
            "state_hz": max(1.0, min(float(hz), 30.0)),
            "camera_hz": max(1.0, min(float(os.getenv("ASV_CAMERA_WS_HZ", "15")), 30.0)),
            "jpeg_quality": max(35, min(int(os.getenv("ASV_CAMERA_JPEG_QUALITY", "75")), 95)),
            "component": "legacy",
        }
        send_lock = asyncio.Lock()

        async def send(payload):
            async with send_lock:
                await websocket.send(payload)

        async def tx():
            next_state = 0.0
            next_camera = 0.0
            frame_sequence = -1
            while True:
                now = time.monotonic()
                if profile["state"] and now >= next_state:
                    await send(json.dumps(store.snapshot(), separators=(",", ":")))
                    next_state = now + 1.0 / profile["state_hz"]
                if profile["camera"] and now >= next_camera:
                    frame, frame_sequence = await asyncio.to_thread(
                        _encode_live_frame, store, profile["jpeg_quality"], frame_sequence
                    )
                    if frame:
                        await send(frame)
                    next_camera = now + 1.0 / profile["camera_hz"]
                await asyncio.sleep(0.005)
        
        async def rx():
            async for raw in websocket:
                cmd = None
                try:
                    if isinstance(raw, bytes):
                        raise ValueError("client tidak boleh mengirim data biner")
                    cmd = json.loads(raw)
                    if isinstance(cmd, dict) and cmd.get("type") == "subscribe":
                        profile["state"] = bool(cmd.get("state", True))
                        profile["camera"] = bool(cmd.get("camera", False))
                        profile["state_hz"] = max(1.0, min(float(cmd.get("state_hz", hz)), 30.0))
                        profile["camera_hz"] = max(1.0, min(float(cmd.get("camera_hz", 15.0)), 30.0))
                        profile["jpeg_quality"] = max(35, min(int(cmd.get("jpeg_quality", 75)), 95))
                        profile["component"] = str(cmd.get("component", "unknown"))[:40]
                        await send(json.dumps({
                            "type": "subscribed",
                            "component": profile["component"],
                            "state": profile["state"],
                            "camera": profile["camera"],
                        }))
                        continue
                    if not isinstance(cmd, dict) or not isinstance(cmd.get("command"), str):
                        raise ValueError("invalid command")
                    
                    store.command(cmd)
                    
                    result = None
                    if command_handler:
                        result = await asyncio.to_thread(command_handler, cmd)
                        
                    await send(json.dumps({"type": "ack", "id": cmd.get("id"), "ok": True, "result": result}))
                except Exception as exc:
                    await send(json.dumps({"type": "ack", "id": cmd.get("id") if isinstance(cmd, dict) else None, "ok": False, "error": str(exc)}))
                    
        tasks = {asyncio.create_task(tx()), asyncio.create_task(rx())}
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def run():
        async with websockets.serve(client, host, port, ping_interval=20, ping_timeout=20, max_size=1_000_000):
            print(f"[WS] ws://{host}:{port}")
            await asyncio.Future()

    threading.Thread(target=lambda: asyncio.run(run()), daemon=True, name="websocket").start()
