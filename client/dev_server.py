"""Development-only static server with browser caching disabled."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os

HOST = "0.0.0.0"
PORT = 8000

class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent)
    print(f"ASV dashboard: http://127.0.0.1:{PORT}/asv-client.html")
    print("Jangan buka asv-client.html melalui file://")
    ThreadingHTTPServer((HOST, PORT), NoCacheHandler).serve_forever()
