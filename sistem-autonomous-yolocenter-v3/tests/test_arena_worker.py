import copy
import importlib.util
import math
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from mod04_state_content import DEFAULT_CONFIG


class StatePalsu:
    def __init__(self):
        self.data = copy.deepcopy(DEFAULT_CONFIG)

    def baca(self):
        return copy.deepcopy(self.data)

    def atur_kunci_arena(self, terkunci, acuan=None):
        self.data["arena"]["acuan_terkunci"] = bool(terkunci)
        if acuan is not None:
            self.data["arena"]["posisi_acuan"] = copy.deepcopy(acuan)
            self.data["arena"]["set_dock_sekarang"] = {
                "lat": float(acuan["lat"]),
                "lon": float(acuan["lon"]),
            }
        return copy.deepcopy(self.data)


class TopikPalsu:
    def berlangganan(self, _topik, _penangan):
        pass

    def mulai(self):
        pass

    def publikasi(self, topik, data):
        self.terakhir = (topik, data)


class ArenaWorkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        modul_topik = types.ModuleType("mod03_robot_topic")
        modul_topik.TOPIK_ARENA = "/tes/arena"
        modul_topik.TOPIK_MAVLINK = "/tes/mavlink"
        modul_topik.TOPIK_PERINTAH = "/tes/perintah"
        modul_topik.robot_topic = TopikPalsu()

        modul_state = types.ModuleType("mod05_state_manager")
        modul_state.state = StatePalsu()

        root = Path(__file__).resolve().parents[1]
        spesifikasi = importlib.util.spec_from_file_location(
            "mod102_arena_untuk_tes",
            root / "mod102_arena_worker.py",
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
        self.state = StatePalsu()
        self.worker = self.modul.ArenaWorker(self.state, TopikPalsu())
        self.worker._terima_mavlink("/tes/mavlink", {
            "gps": {
                "fix": True,
                "lat": -7.0,
                "lon": 110.0,
                "heading": 90.0,
            },
            "orientation": {"z": math.pi / 2},
            "mode": "MANUAL",
            "arm": "Disarmed",
        })
        self.worker._sinkron_cold()

    def atur_status_arena(self, status):
        self.state.data["missionState"] = status
        self.worker.waktu_baca_cold = 0.0
        self.worker._sinkron_cold()
        self.worker._sinkron_status_misi()

    def test_trigger_misi_mengunci_dock_tanpa_peduli_mode(self):
        self.atur_status_arena("RUNNING")
        self.worker._perbarui_posisi()
        arena = self.worker.snapshot()["arena"]

        self.assertTrue(arena["dimulai"])
        self.assertTrue(arena["berjalan"])
        self.assertEqual(arena["posisi_sekarang"]["x"], 20.5)
        self.assertEqual(arena["posisi_sekarang"]["y"], 0.0)
        self.assertEqual(arena["posisi_acuan"]["heading"], 90.0)
        self.assertEqual(arena["posisi_acuan"]["arena"], "A")
        self.assertEqual(arena["set_dock_sekarang"], {"lat": -7.0, "lon": 110.0})
        self.assertEqual(len(arena["riwayat_pergerakan"]), 1)
        self.assertIn("A", arena)
        self.assertIn("B", arena)

    def test_acuan_tidak_berubah_selama_misi_berjalan(self):
        self.atur_status_arena("RUNNING")
        acuan_awal = copy.deepcopy(self.state.data["arena"]["posisi_acuan"])

        self.worker._terima_mavlink("/tes/mavlink", {
            "gps": {"lat": -7.001, "lon": 110.001, "heading": 180.0},
        })
        self.worker._sinkron_status_misi()

        self.assertEqual(self.state.data["arena"]["posisi_acuan"], acuan_awal)

    def test_restart_worker_di_tengah_misi_memakai_acuan_yang_sama(self):
        self.atur_status_arena("RUNNING")
        acuan_awal = copy.deepcopy(self.state.data["arena"]["posisi_acuan"])

        worker_baru = self.modul.ArenaWorker(self.state, TopikPalsu())
        worker_baru._terima_mavlink("/tes/mavlink", {
            "gps": {
                "fix": True,
                "lat": -7.001,
                "lon": 110.001,
                "heading": 180.0,
            },
        })
        worker_baru._sinkron_cold()
        worker_baru._sinkron_status_misi()

        self.assertEqual(self.state.data["arena"]["posisi_acuan"], acuan_awal)

    def test_jeda_mempertahankan_kunci_dan_selesai_membukanya(self):
        self.atur_status_arena("RUNNING")

        self.atur_status_arena("PAUSED")
        self.assertTrue(self.state.data["arena"]["acuan_terkunci"])

        self.atur_status_arena("STOPPED")
        self.assertFalse(self.state.data["arena"]["acuan_terkunci"])

    def test_clear_history_tidak_menghapus_posisi_sekarang(self):
        self.atur_status_arena("RUNNING")
        self.worker._perbarui_posisi()

        self.worker._terima_perintah("/tes/perintah", {"command": "clear_history"})
        arena = self.worker.snapshot()["arena"]

        self.assertEqual(arena["riwayat_pergerakan"], [])
        self.assertIsNotNone(arena["posisi_sekarang"])

    def test_mode_dan_arm_tidak_menghentikan_arena(self):
        self.atur_status_arena("RUNNING")

        self.worker._terima_mavlink("/tes/mavlink", {
            "arm": "Disarmed",
            "mode": "MANUAL",
        })
        self.worker._sinkron_status_misi()

        arena = self.worker.snapshot()["arena"]
        self.assertTrue(arena["dimulai"])
        self.assertEqual(arena["status"], "berjalan")

    def test_visualisasi_memuat_batas_buoy_kotak_dan_docking(self):
        self.atur_status_arena("RUNNING")
        visualisasi = self.worker.snapshot()["arena"]["visualisasi"]

        self.assertEqual(visualisasi["nama"], "A")
        self.assertEqual(len(visualisasi["batas"]), 4)
        self.assertEqual(len(visualisasi["buoy"]["merah"]), 10)
        self.assertEqual(len(visualisasi["buoy"]["hijau"]), 10)
        self.assertEqual(len(visualisasi["docking"]), 3)
        self.assertIn("lat", visualisasi["kotak"]["biru"])
        self.assertIn("lon", visualisasi["kotak"]["biru"])

if __name__ == "__main__":
    unittest.main()
