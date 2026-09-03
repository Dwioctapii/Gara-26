"""HTTP worker: endpoint /api/command, /health, dan /foto/*."""

from __future__ import annotations

import http.server
import json
import threading
from urllib.parse import urlparse
from pathlib import Path

from server_common import _debug


def start_http(host: str, port: int, store, photo_dir: Path, command_handler=None) -> None:
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

        def _send_file(self, path: Path, mime: str):
            try:
                data = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self._json({"error": str(e)}, 404)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/health":
                self._json({"ok": True, "service": "sistem-autonomous-waypoint"})
                return
            # ─── Endpoint foto ───────────────────────────────────────
            if path.startswith("/foto/"):
                filename = path.split("/")[-1]
                if filename not in ("atas.jpg", "bawah.jpg"):
                    self._json({"error": "invalid filename"}, 400)
                    return
                filepath = photo_dir / filename
                if not filepath.is_file():
                    self._json({"error": "file not found"}, 404)
                    return
                self._send_file(filepath, "image/jpeg")
                return
            self._json({"error": "HTTP hanya untuk request/perintah dan foto"}, 405)

        def do_POST(self):
            path = urlparse(self.path).path
            if path != "/api/command":
                return self._json({"ok": False, "error": "not found"}, 404)
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length < 2 or content_length > 65536:
                    raise ValueError("ukuran request tidak valid")
                command = json.loads(self.rfile.read(content_length))
                if not isinstance(command, dict) or not isinstance(command.get("command"), str):
                    raise ValueError("command tidak valid")
                _debug("HTTP-COMMAND", "request_received", command)
                store.command(command)
                result = command_handler(command) if command_handler else None
                response = {"ok": True, "id": command.get("id"), "result": result}
                _debug("HTTP-COMMAND", "response_sent", response)
                self._json(response)
            except Exception as error:
                response = {"ok": False, "error": str(error)}
                _debug("HTTP-COMMAND", "request_failed", response)
                self._json(response, 400)

        def log_message(self, fmt, *args):
            print("[HTTP] " + fmt % args)

    server = http.server.ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="http").start()
    print(f"[HTTP] http://{host}:{port}")
    print(f"[HTTP] Foto tersedia di http://{host}:{port}/foto/atas.jpg")