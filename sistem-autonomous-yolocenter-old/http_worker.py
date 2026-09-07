"""HTTP worker: endpoint /api/command dan /health."""

from __future__ import annotations

import http.server
import json
import threading
from urllib.parse import urlparse

from server_common import _debug


def start_http(host: str, port: int, store, command_handler=None) -> None:
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

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/health":
                self._json({"ok": True, "service": "sistem-autonomous-waypoint"})
            else:
                self._json({"error": "HTTP hanya untuk request/perintah"}, 405)

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