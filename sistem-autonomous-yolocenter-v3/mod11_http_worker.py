"""HTTP kecil untuk health, perintah, dan foto hasil deteksi."""

from __future__ import annotations

import http.server
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import mod01_config as config
from mod03_robot_topic import TOPIK_PERINTAH, TOPIK_PERINTAH_VISION, robot_topic
from mod05_state_manager import state


class HttpWorker:
    """Melayani endpoint HTTP tanpa menyimpan hot state sendiri."""

    def __init__(
        self,
        host: str,
        port: int,
        direktori_foto: Path,
        penyimpan=state,
        topik=robot_topic,
    ) -> None:
        self.host = host
        self.port = port
        self.direktori_foto = direktori_foto
        self.penyimpan = penyimpan
        self.topik = topik

    def buat_server(self):
        direktori_foto = self.direktori_foto
        penyimpan = self.penyimpan
        topik = self.topik

        class Handler(http.server.BaseHTTPRequestHandler):
            def kirim_json(self, isi, kode=200):
                muatan = json.dumps(isi, ensure_ascii=False).encode()
                self.send_response(kode)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(muatan)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(muatan)

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def do_GET(self):
                alamat = urlparse(self.path)
                jalur = alamat.path
                if jalur == "/health":
                    self.kirim_json({"ok": True, "service": "asv-autonomous"})
                    return
                if jalur == "/api/rahasia":
                    self.proses_api_rahasia(parse_qs(alamat.query, keep_blank_values=True))
                    return
                if not jalur.startswith("/foto/"):
                    self.kirim_json({"ok": False, "error": "tidak ditemukan"}, 404)
                    return

                nama = jalur.rsplit("/", 1)[-1]
                if nama not in {"atas.jpg", "bawah.jpg"}:
                    self.kirim_json({"ok": False, "error": "nama foto tidak valid"}, 400)
                    return
                berkas = direktori_foto / nama
                if not berkas.is_file():
                    self.kirim_json({"ok": False, "error": "foto belum tersedia"}, 404)
                    return
                isi = berkas.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(isi)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(isi)

            def proses_api_rahasia(self, parameter):
                aksi = [
                    nama for nama in ("tahan_foto", "foto_sekarang", "reset_foto")
                    if nama in parameter
                ]
                if len(aksi) != 1:
                    self.kirim_json({"ok": False, "error": "gunakan tepat satu perintah foto"}, 400)
                    return

                nama = aksi[0]
                if nama == "tahan_foto":
                    teks = parameter[nama][-1].strip().lower()
                    if teks not in {"true", "false"}:
                        self.kirim_json({"ok": False, "error": "tahan_foto harus true atau false"}, 400)
                        return
                    ditahan = teks == "true"
                    penyimpan.atur_tahan_foto(ditahan)
                    topik.publikasi(
                        TOPIK_PERINTAH_VISION,
                        {"command": "tahan_foto", "nilai": ditahan},
                        dipertahankan=False,
                    )
                    self.kirim_json({"ok": True, "tahan_foto": ditahan})
                    return

                if nama == "foto_sekarang":
                    kamera = parameter[nama][-1].strip().lower()
                    if kamera not in {"atas", "bawah"}:
                        self.kirim_json({"ok": False, "error": "kamera harus atas atau bawah"}, 400)
                        return
                    if penyimpan.baca().get("tahan_foto", False):
                        self.kirim_json({"ok": False, "error": "foto sedang ditahan"}, 409)
                        return
                    topik.publikasi(
                        TOPIK_PERINTAH_VISION,
                        {"command": "foto_sekarang", "kamera": kamera},
                        dipertahankan=False,
                    )
                    self.kirim_json({"ok": True, "queued": True, "kamera": kamera})
                    return

                penyimpan.reset_status_foto()
                topik.publikasi(
                    TOPIK_PERINTAH_VISION,
                    {"command": "reset_foto"},
                    dipertahankan=False,
                )
                self.kirim_json({"ok": True, "queued": True, "reset_foto": True})

            def do_POST(self):
                if urlparse(self.path).path != "/api/command":
                    self.kirim_json({"ok": False, "error": "tidak ditemukan"}, 404)
                    return
                try:
                    panjang = int(self.headers.get("Content-Length", "0"))
                    if not 2 <= panjang <= 65_536:
                        raise ValueError("ukuran request tidak valid")
                    perintah = json.loads(self.rfile.read(panjang))
                    if not isinstance(perintah, dict) or not isinstance(perintah.get("command"), str):
                        raise ValueError("perintah tidak valid")
                    topik.publikasi(TOPIK_PERINTAH, perintah, dipertahankan=False)
                    self.kirim_json({"ok": True, "id": perintah.get("id"), "queued": True})
                except (ValueError, json.JSONDecodeError) as galat:
                    self.kirim_json({"ok": False, "error": str(galat)}, 400)

            def log_message(self, format_pesan, *argumen):
                print(format_pesan % argumen)

        return http.server.ThreadingHTTPServer((self.host, self.port), Handler)

    def jalankan(self) -> None:
        server = self.buat_server()
        print(f"HTTP aktif di http://{self.host}:{self.port}")
        server.serve_forever()


def main() -> None:
    config.PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    robot_topic.mulai()
    HttpWorker(config.HTTP_HOST, config.HTTP_PORT, config.PHOTO_DIR).jalankan()


if __name__ == "__main__":
    main()
