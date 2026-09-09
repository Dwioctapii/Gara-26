import importlib.util
import json
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen


class ClientServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        spesifikasi = importlib.util.spec_from_file_location(
            "server_client_untuk_tes",
            root / "client" / "server_client.py",
        )
        cls.modul = importlib.util.module_from_spec(spesifikasi)
        spesifikasi.loader.exec_module(cls.modul)

    def setUp(self):
        self.server = self.modul.ClientServer(("127.0.0.1", 0), self.modul.ClientHandler)
        self.utas = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.utas.start()
        self.alamat = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.utas.join(timeout=2)

    def test_root_melayani_dashboard(self):
        with urlopen(f"{self.alamat}/", timeout=2) as respons:
            isi = respons.read().decode()

        self.assertEqual(respons.status, 200)
        self.assertIn("disableLocalToggle", isi)
        self.assertIn('id="kunciHeadingKompasToggle" type="checkbox" checked', isi)

    def test_health_client_terpisah(self):
        with urlopen(f"{self.alamat}/health", timeout=2) as respons:
            isi = json.loads(respons.read())

        self.assertEqual(isi, {"ok": True, "service": "asv-client"})

    def test_secret_melayani_kendali_internal(self):
        with urlopen(f"{self.alamat}/secret", timeout=2) as respons:
            isi = respons.read().decode()

        self.assertEqual(respons.status, 200)
        self.assertIn("ASV Control Rahasia", isi)
        self.assertIn('id="statusState"', isi)
        self.assertIn("/secret.js", isi)

        for aset in ("/secret.css", "/secret.js", "/index.html"):
            with self.subTest(aset=aset), urlopen(f"{self.alamat}{aset}", timeout=2) as respons:
                self.assertEqual(respons.status, 200)

        with urlopen(f"{self.alamat}/secret.js", timeout=2) as respons:
            javascript = respons.read().decode()
        self.assertIn("/local_scope/gui/state", javascript)
        self.assertIn("/sistem_broadcast/state_dan_variabel", javascript)

    def test_secret_html_dan_sumber_server_tidak_dapat_diakses_langsung(self):
        for jalur in ("/secret.html", "/server_client.py"):
            with self.subTest(jalur=jalur), self.assertRaises(HTTPError) as galat:
                urlopen(f"{self.alamat}{jalur}", timeout=2)
            self.assertEqual(galat.exception.code, 404)

    def test_daftar_direktori_ditolak(self):
        with self.assertRaises(HTTPError) as galat:
            urlopen(f"{self.alamat}/data/", timeout=2)

        self.assertEqual(galat.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
