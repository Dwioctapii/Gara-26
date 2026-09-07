import importlib.util
import json
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen


class StatePalsu:
    def __init__(self):
        self.data = {
            "tahan_foto": False,
            "foto": {
                "atas": {"tersedia": True, "revisi": 1},
                "bawah": {"tersedia": True, "revisi": 1},
            },
        }

    def baca(self):
        return self.data

    def atur_tahan_foto(self, ditahan):
        self.data["tahan_foto"] = ditahan

    def reset_status_foto(self):
        for status in self.data["foto"].values():
            status["tersedia"] = False


class TopikPalsu:
    def __init__(self):
        self.publikasi_terakhir = None

    def publikasi(self, topik, data, dipertahankan):
        self.publikasi_terakhir = (topik, data, dipertahankan)


class HttpWorkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        modul_topik = types.ModuleType("mod03_robot_topic")
        modul_topik.TOPIK_PERINTAH = "/tes/perintah"
        modul_topik.TOPIK_PERINTAH_VISION = "/tes/vision/command"
        modul_topik.robot_topic = TopikPalsu()

        modul_state = types.ModuleType("mod05_state_manager")
        modul_state.state = StatePalsu()

        root = Path(__file__).resolve().parents[1]
        spesifikasi = importlib.util.spec_from_file_location(
            "mod11_http_untuk_tes",
            root / "mod11_http_worker.py",
        )
        cls.modul = importlib.util.module_from_spec(spesifikasi)
        with patch.dict(
            sys.modules,
            {
                "mod03_robot_topic": modul_topik,
                "mod05_state_manager": modul_state,
            },
        ):
            spesifikasi.loader.exec_module(cls.modul)

    def setUp(self):
        self.direktori_sementara = tempfile.TemporaryDirectory()
        self.state = StatePalsu()
        self.topik = TopikPalsu()
        worker = self.modul.HttpWorker(
            "127.0.0.1",
            0,
            Path(self.direktori_sementara.name),
            penyimpan=self.state,
            topik=self.topik,
        )
        self.server = worker.buat_server()
        self.utas = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.utas.start()
        self.alamat = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.utas.join(timeout=2)
        self.direktori_sementara.cleanup()

    def ambil_json(self, query):
        with urlopen(f"{self.alamat}/api/rahasia?{query}", timeout=2) as respons:
            return respons.status, json.loads(respons.read())

    def test_tahan_foto_disimpan_dan_dikirim_ke_vision(self):
        kode, isi = self.ambil_json("tahan_foto=true")

        self.assertEqual(kode, 200)
        self.assertTrue(isi["tahan_foto"])
        self.assertTrue(self.state.data["tahan_foto"])
        self.assertEqual(
            self.topik.publikasi_terakhir,
            ("/tes/vision/command", {"command": "tahan_foto", "nilai": True}, False),
        )

    def test_foto_sekarang_ditolak_saat_ditahan(self):
        self.state.data["tahan_foto"] = True

        with self.assertRaises(HTTPError) as galat:
            self.ambil_json("foto_sekarang=atas")

        self.assertEqual(galat.exception.code, 409)
        self.assertIsNone(self.topik.publikasi_terakhir)

    def test_foto_sekarang_bawah_dikirim_ke_vision(self):
        kode, isi = self.ambil_json("foto_sekarang=bawah")

        self.assertEqual(kode, 200)
        self.assertEqual(isi["kamera"], "bawah")
        self.assertEqual(
            self.topik.publikasi_terakhir,
            ("/tes/vision/command", {"command": "foto_sekarang", "kamera": "bawah"}, False),
        )

    def test_reset_foto_mereset_state_dan_dikirim_ke_vision(self):
        kode, isi = self.ambil_json("reset_foto")

        self.assertEqual(kode, 200)
        self.assertTrue(isi["reset_foto"])
        self.assertFalse(self.state.data["foto"]["atas"]["tersedia"])
        self.assertFalse(self.state.data["foto"]["bawah"]["tersedia"])
        self.assertEqual(
            self.topik.publikasi_terakhir,
            ("/tes/vision/command", {"command": "reset_foto"}, False),
        )


if __name__ == "__main__":
    unittest.main()
