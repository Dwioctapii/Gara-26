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

    def test_misi_mavlink_mengunci_titik_mulai_dan_heading(self):
        self.worker._terima_mavlink("/tes/mavlink", {
            "missionState": "RUNNING",
            "mode": "AUTO",
            "arm": "Armed",
        })
        self.worker._sinkron_status_misi()
        self.worker._perbarui_posisi()
        arena = self.worker.snapshot()["arena"]

        self.assertTrue(arena["dimulai"])
        self.assertTrue(arena["berjalan"])
        self.assertEqual(arena["posisi_sekarang"]["x"], 20.5)
        self.assertEqual(arena["posisi_sekarang"]["y"], 0.0)
        self.assertEqual(arena["posisi_acuan"]["heading"], 90.0)
        self.assertEqual(arena["posisi_acuan"]["arena"], "A")
        self.assertEqual(len(arena["riwayat_pergerakan"]), 1)
        self.assertIn("A", arena)
        self.assertIn("B", arena)

    def test_acuan_tidak_berubah_selama_misi_berjalan(self):
        self.worker._terima_mavlink("/tes/mavlink", {
            "missionState": "RUNNING",
            "mode": "AUTO",
            "arm": "Armed",
        })
        self.worker._sinkron_status_misi()
        acuan_awal = copy.deepcopy(self.state.data["arena"]["posisi_acuan"])

        self.worker._terima_mavlink("/tes/mavlink", {
            "gps": {"lat": -7.001, "lon": 110.001, "heading": 180.0},
        })
        self.worker._sinkron_status_misi()

        self.assertEqual(self.state.data["arena"]["posisi_acuan"], acuan_awal)

    def test_restart_worker_di_tengah_misi_memakai_acuan_yang_sama(self):
        self.worker._terima_mavlink("/tes/mavlink", {
            "missionState": "RUNNING",
            "mode": "AUTO",
            "arm": "Armed",
        })
        self.worker._sinkron_status_misi()
        acuan_awal = copy.deepcopy(self.state.data["arena"]["posisi_acuan"])

        worker_baru = self.modul.ArenaWorker(self.state, TopikPalsu())
        worker_baru._terima_mavlink("/tes/mavlink", {
            "missionState": "RUNNING",
            "mode": "AUTO",
            "arm": "Armed",
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
        self.worker._terima_mavlink("/tes/mavlink", {
            "missionState": "RUNNING",
            "mode": "AUTO",
            "arm": "Armed",
        })
        self.worker._sinkron_status_misi()

        self.worker._terima_mavlink("/tes/mavlink", {"missionState": "PAUSED"})
        self.worker._sinkron_status_misi()
        self.assertTrue(self.state.data["arena"]["acuan_terkunci"])

        self.worker._terima_mavlink("/tes/mavlink", {"missionState": "COMPLETED"})
        self.worker._sinkron_status_misi()
        self.assertFalse(self.state.data["arena"]["acuan_terkunci"])

    def test_clear_history_tidak_menghapus_posisi_sekarang(self):
        self.worker._terima_mavlink("/tes/mavlink", {
            "missionState": "RUNNING",
            "mode": "AUTO",
            "arm": "Armed",
        })
        self.worker._sinkron_status_misi()
        self.worker._perbarui_posisi()

        self.worker._terima_perintah("/tes/perintah", {"command": "clear_history"})
        arena = self.worker.snapshot()["arena"]

        self.assertEqual(arena["riwayat_pergerakan"], [])
        self.assertIsNotNone(arena["posisi_sekarang"])

    def test_disarm_mengakhiri_status_running_yang_tertinggal(self):
        self.worker._terima_mavlink("/tes/mavlink", {
            "missionState": "RUNNING",
            "mode": "AUTO",
            "arm": "Armed",
        })
        self.worker._sinkron_status_misi()

        self.worker._terima_mavlink("/tes/mavlink", {"arm": "Disarmed"})
        self.worker._sinkron_status_misi()

        arena = self.worker.snapshot()["arena"]
        self.assertFalse(arena["dimulai"])
        self.assertEqual(arena["status"], "berhenti")

if __name__ == "__main__":
    unittest.main()
