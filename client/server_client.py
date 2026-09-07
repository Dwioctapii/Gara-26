"""HTTP statis khusus dashboard web pada port terpisah dari API robot."""

from __future__ import annotations

import http.server
import json
import os
from pathlib import Path
from urllib.parse import urlparse


ROOT_CLIENT = Path(__file__).resolve().parent
HOST_CLIENT = os.getenv("ASV_CLIENT_HOST", "0.0.0.0")
PORT_CLIENT = int(os.getenv("ASV_CLIENT_PORT", "8767"))


class ClientHandler(http.server.SimpleHTTPRequestHandler):
    """Melayani index dan aset dashboard tanpa membuka daftar direktori."""

    def __init__(self, *argumen, **opsi) -> None:
        super().__init__(*argumen, directory=str(ROOT_CLIENT), **opsi)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def do_GET(self) -> None:
        jalur = urlparse(self.path).path
        if jalur == "/health":
            isi = json.dumps({"ok": True, "service": "asv-client"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(isi)))
            self.end_headers()
            self.wfile.write(isi)
            return
        if jalur == "/":
            self.path = "/index.html"
        elif jalur.endswith("/"):
            self.send_error(404, "Route tidak ditemukan")
            return
        super().do_GET()

    def list_directory(self, _jalur):
        self.send_error(404, "Route tidak ditemukan")
        return None

    def log_message(self, format_pesan, *argumen) -> None:
        print(f"[CLIENT-HTTP] {format_pesan % argumen}", flush=True)


class ClientServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True


def main() -> None:
    server = ClientServer((HOST_CLIENT, PORT_CLIENT), ClientHandler)
    print(
        f"[CLIENT-HTTP] Dashboard aktif di http://{HOST_CLIENT}:{PORT_CLIENT}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
