import multiprocessing
import tempfile
import unittest
from pathlib import Path

from mod04_state_content import ARENA_A, DEFAULT_ARENA_A, DEFAULT_ARENA_B
from mod05_state_manager import StateManager


def tulis_cold_state(jalur, perubahan):
    StateManager(jalur).perbarui(perubahan)


class StateManagerTest(unittest.TestCase):
    def test_arena_default_dan_cerminan_tersedia(self):
        with tempfile.TemporaryDirectory() as direktori:
            hasil = StateManager(Path(direktori) / "state.json").baca()

        self.assertEqual(hasil["arena"]["A"], DEFAULT_ARENA_A)
        self.assertEqual(hasil["arena"]["B"], DEFAULT_ARENA_B)
        self.assertEqual(len(hasil["arena"]["A"]["docking"]), 3)
        self.assertEqual(
            hasil["arena"]["B"]["kotak"]["merah"]["x"],
            30.0 - hasil["arena"]["A"]["kotak"]["merah"]["x"],
        )

    def test_arena_aktif_bukan_objek_default(self):
        self.assertIsNot(ARENA_A, DEFAULT_ARENA_A)
        self.assertIsNot(ARENA_A["buoy"]["merah"], DEFAULT_ARENA_A["buoy"]["merah"])

    def test_tahan_foto_default_false_dan_dapat_diubah(self):
        with tempfile.TemporaryDirectory() as direktori:
            state = StateManager(Path(direktori) / "state.json")
            self.assertFalse(state.baca()["tahan_foto"])

            state.atur_tahan_foto(True)

            self.assertTrue(state.baca()["tahan_foto"])

    def test_kunci_dan_posisi_acuan_arena_tersimpan_atomik(self):
        with tempfile.TemporaryDirectory() as direktori:
            state = StateManager(Path(direktori) / "state.json")
            state.atur_kunci_arena(True, {
                "x": 2,
                "y": 3,
                "lat": -7.1,
                "lon": 110.3,
                "heading": 90,
                "timestamp": 123,
                "arena": "B",
            })

            arena = state.baca()["arena"]
            acuan = arena["posisi_acuan"]

            self.assertTrue(arena["acuan_terkunci"])
            self.assertEqual(acuan["x"], 2.0)
            self.assertEqual(acuan["y"], 3.0)
            self.assertEqual(acuan["heading"], 90.0)
            self.assertEqual(acuan["arena"], "B")

    def test_cold_state_tersimpan_dan_dimuat_ulang(self):
        with tempfile.TemporaryDirectory() as direktori:
            jalur = Path(direktori) / "state.json"
            state = StateManager(jalur)
            state.perbarui({"currentTrack": "C", "loggerActive": True})

            hasil = StateManager(jalur).baca()

            self.assertEqual(hasil["currentTrack"], "C")
            self.assertTrue(hasil["loggerActive"])
            self.assertFalse(jalur.with_suffix(".json.lock").exists())

    def test_pid_divalidasi_dan_versi_naik(self):
        with tempfile.TemporaryDirectory() as direktori:
            state = StateManager(Path(direktori) / "state.json")
            state.terapkan_perintah({
                "command": "set_pid",
                "kp": 3,
                "ki": 0.1,
                "kd": 1,
                "deadband": 4,
                "integral_limit": 90,
            })

            pid = state.pid_snapshot()

            self.assertEqual(pid["kp"], 3)
            self.assertEqual(pid["_version"], 1)

    def test_lock_mencegah_tulis_antarproses_saling_menimpa(self):
        with tempfile.TemporaryDirectory() as direktori:
            jalur = Path(direktori) / "state.json"
            StateManager(jalur)
            konteks = multiprocessing.get_context("spawn")
            proses_track = konteks.Process(
                target=tulis_cold_state,
                args=(jalur, {"currentTrack": "D"}),
            )
            proses_logger = konteks.Process(
                target=tulis_cold_state,
                args=(jalur, {"loggerActive": True}),
            )

            proses_track.start()
            proses_logger.start()
            proses_track.join(5)
            proses_logger.join(5)
            hasil = StateManager(jalur).baca()

            self.assertEqual(proses_track.exitcode, 0)
            self.assertEqual(proses_logger.exitcode, 0)
            self.assertEqual(hasil["currentTrack"], "D")
            self.assertTrue(hasil["loggerActive"])

    def test_status_foto_tersimpan_dan_revisi_naik(self):
        with tempfile.TemporaryDirectory() as direktori:
            state = StateManager(Path(direktori) / "state.json")

            state.atur_status_foto("atas", True)
            hasil = StateManager(state.jalur).status_foto()

            self.assertTrue(hasil["atas"]["tersedia"])
            self.assertEqual(hasil["atas"]["revisi"], 1)

            state.reset_status_foto()
            hasil = state.status_foto()

            self.assertFalse(hasil["atas"]["tersedia"])
            self.assertEqual(hasil["atas"]["revisi"], 2)


if __name__ == "__main__":
    unittest.main()
