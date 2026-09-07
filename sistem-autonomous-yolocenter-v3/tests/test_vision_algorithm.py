import copy
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


DEPENDENCY_TERSEDIA = (
    importlib.util.find_spec("cv2") is not None
    and importlib.util.find_spec("numpy") is not None
)


@unittest.skipUnless(DEPENDENCY_TERSEDIA, "dependency vision belum terpasang")
class VisionAlgorithmTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        modul_topik = types.ModuleType("mod03_robot_topic")
        modul_topik.TOPIK_FRAME = "/tes/frame"
        modul_topik.TOPIK_PERINTAH_VISION = "/tes/vision/command"
        modul_topik.TOPIK_VISION = "/tes/vision"
        modul_topik.robot_topic = object()

        modul_state = types.ModuleType("mod05_state_manager")
        modul_state.state = object()

        modul_yolo = types.ModuleType("ultralytics")
        modul_yolo.YOLO = None

        root = Path(__file__).resolve().parents[1]
        spesifikasi = importlib.util.spec_from_file_location(
            "mod08_vision_untuk_tes",
            root / "mod08_vision_worker.py",
        )
        cls.modul = importlib.util.module_from_spec(spesifikasi)
        with patch.dict(
            sys.modules,
            {
                "mod03_robot_topic": modul_topik,
                "mod05_state_manager": modul_state,
                "ultralytics": modul_yolo,
            },
        ):
            spesifikasi.loader.exec_module(cls.modul)
        cls.np = cls.modul.np

    def test_device_yolo_dapat_gpu_cpu_atau_auto(self):
        self.assertEqual(self.modul._perangkat_yolo("0"), 0)
        self.assertEqual(self.modul._perangkat_yolo("cpu"), "cpu")
        self.assertIsNone(self.modul._perangkat_yolo("auto"))

    def test_pipeline_dikunci_640(self):
        self.assertEqual(self.modul.config.CAMERA_WIDTH, 640)
        self.assertEqual(self.modul.config.CAMERA_HEIGHT, 480)
        self.assertEqual(self.modul.config.YOLO_IMAGE_SIZE, 640)

    def test_pid_tidak_memberi_lonjakan_derivatif_pada_sampel_pertama(self):
        pid = self.modul.BuoyPIDController(0, 0, 1, 100, 0, 1500, 1100, 1900)

        pwm, rincian = pid.compute(100)

        self.assertEqual(rincian["d"], 0.0)
        self.assertEqual(pwm, 1500)

    def test_boxblue_dideteksi_di_atas_dan_menyimpan_kamera_bawah(self):
        class PenyimpanPalsu:
            def cold_snapshot(self):
                return {
                    "pid_config": {"_version": 0},
                    "tahan_foto": False,
                    "foto": {
                        "atas": {"tersedia": False},
                        "bawah": {"tersedia": False},
                    },
                }

            def tandai_foto(self, kamera, tersedia):
                self.foto = (kamera, tersedia)

            def update(self, _perubahan):
                pass

            def set_live_frame(self, _bingkai):
                pass

        class KotakPalsu:
            cls = self.np.array([0])
            xywh = self.np.array([[200.0, 240.0, 160.0, 160.0]])

        class HasilPalsu:
            boxes = [KotakPalsu()]

        class ModelPalsu:
            names = {0: "boxblue"}

            def __call__(self, bingkai, **_opsi):
                self.bingkai = bingkai
                return [HasilPalsu()]

        penyimpan = PenyimpanPalsu()
        worker = self.modul.VisionWorker(0, 1, Path("best.pt"), Path("."), penyimpan)
        kamera_atas = self.np.zeros((480, 640, 3), dtype=self.np.uint8)
        kamera_bawah = self.np.ones((480, 640, 3), dtype=self.np.uint8)
        model = ModelPalsu()

        with patch.object(self.modul.cv2, "imwrite", return_value=True) as simpan:
            worker._deteksi(model, kamera_atas, kamera_bawah)

        jalur, gambar = simpan.call_args.args
        self.assertIs(model.bingkai, kamera_atas)
        self.assertTrue(jalur.endswith("bawah.jpg"))
        self.assertIs(gambar, kamera_bawah)
        self.assertEqual(penyimpan.foto, ("bawah", True))

    def test_foto_manual_memakai_kamera_yang_diminta(self):
        class PenyimpanPalsu:
            def cold_snapshot(self):
                return {"tahan_foto": False}

            def tandai_foto(self, kamera, tersedia):
                self.foto = (kamera, tersedia)

            def update(self, _perubahan):
                pass

        penyimpan = PenyimpanPalsu()
        worker = self.modul.VisionWorker(0, 1, Path("best.pt"), Path("."), penyimpan)
        kamera_atas = self.np.zeros((480, 640, 3), dtype=self.np.uint8)
        kamera_bawah = self.np.ones((480, 640, 3), dtype=self.np.uint8)
        worker._terima_perintah_foto(
            "/tes/vision/command",
            {"command": "foto_sekarang", "kamera": "bawah"},
        )

        with patch.object(self.modul.cv2, "imwrite", return_value=True) as simpan:
            worker._proses_perintah_foto(kamera_atas, kamera_bawah)

        jalur, gambar = simpan.call_args.args
        self.assertTrue(jalur.endswith("bawah.jpg"))
        self.assertIs(gambar, kamera_bawah)
        self.assertEqual(penyimpan.foto, ("bawah", True))

    def test_foto_manual_diblokir_oleh_tahan_foto(self):
        class PenyimpanPalsu:
            def cold_snapshot(self):
                return {"tahan_foto": True}

            def update(self, _perubahan):
                pass

        worker = self.modul.VisionWorker(0, 1, Path("best.pt"), Path("."), PenyimpanPalsu())
        bingkai = self.np.zeros((480, 640, 3), dtype=self.np.uint8)
        worker._terima_perintah_foto(
            "/tes/vision/command",
            {"command": "foto_sekarang", "kamera": "atas"},
        )

        with patch.object(self.modul.cv2, "imwrite") as simpan:
            worker._proses_perintah_foto(bingkai, bingkai)

        simpan.assert_not_called()

    def test_objek_hilang_mereset_area_dan_koordinat(self):
        class PenyimpanPalsu:
            def __init__(self):
                self.data = {
                    "detection": {"label": "STANDBY", "area_green": 0, "area_blue": 0},
                    "buoy": {"mode": "NONE", "cx_red": 0, "cx_green": 0},
                }
                self.cold = {
                    "pid_config": {"_version": 0},
                    "tahan_foto": False,
                    "foto": {
                        "atas": {"tersedia": False},
                        "bawah": {"tersedia": False},
                    },
                }

            def cold_snapshot(self):
                return copy.deepcopy(self.cold)

            def update(self, perubahan):
                self._gabungkan(self.data, perubahan)

            def _gabungkan(self, target, perubahan):
                for kunci, nilai in perubahan.items():
                    if isinstance(nilai, dict) and isinstance(target.get(kunci), dict):
                        self._gabungkan(target[kunci], nilai)
                    else:
                        target[kunci] = copy.deepcopy(nilai)

            def set_live_frame(self, _bingkai):
                pass

        class KotakPalsu:
            cls = self.np.array([0])
            xywh = self.np.array([[200.0, 240.0, 60.0, 60.0]])

        class HasilPalsu:
            boxes = [KotakPalsu()]

        class ModelPalsu:
            names = {0: "buoyred"}

            def __init__(self):
                self.ada_objek = True
                self.opsi = None

            def __call__(self, _bingkai, **_opsi):
                self.opsi = _opsi
                return [HasilPalsu()] if self.ada_objek else []

        penyimpan = PenyimpanPalsu()
        worker = self.modul.VisionWorker(0, 1, Path("best.pt"), Path("."), penyimpan)
        bingkai = self.np.zeros((480, 640, 3), dtype=self.np.uint8)
        model = ModelPalsu()

        worker._deteksi(model, bingkai, bingkai)
        self.assertEqual(penyimpan.data["buoy"]["mode"], "RED_ONLY")
        self.assertEqual(model.opsi["conf"], self.modul.config.YOLO_CONFIDENCE)
        self.assertEqual(model.opsi["imgsz"], self.modul.config.YOLO_IMAGE_SIZE)
        self.assertTrue(model.opsi["agnostic_nms"])

        model.ada_objek = False
        worker._deteksi(model, bingkai, bingkai)

        self.assertEqual(penyimpan.data["detection"]["area_blue"], 0)
        self.assertEqual(penyimpan.data["detection"]["area_green"], 0)
        self.assertEqual(penyimpan.data["buoy"]["mode"], "NONE")
        self.assertEqual(penyimpan.data["buoy"]["cx_red"], 0)
        self.assertEqual(penyimpan.data["buoy"]["cx_green"], 0)


if __name__ == "__main__":
    unittest.main()
