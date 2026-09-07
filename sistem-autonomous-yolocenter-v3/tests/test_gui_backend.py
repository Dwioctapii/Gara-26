import base64
import unittest

from gui.websocket import GUIWebSocket
from mod09_broadcast_ws_client_worker import GuiStateWorker


class GuiBackendTest(unittest.TestCase):
    def test_snapshot_mempertahankan_skema_frontend(self):
        worker = GuiStateWorker()
        worker._terima_data_panas("/local_scope/mavlink/state", {
            "mode": "AUTO",
            "gps": {"lat": -6.2, "lon": 106.8},
        })

        hasil = worker.snapshot()

        self.assertEqual(hasil["mode"], "AUTO")
        self.assertEqual(hasil["lat"], -6.2)
        self.assertIn("battery1", hasil)
        self.assertIn("buoy", hasil)
        self.assertIn("waypoints", hasil["mission"])
        self.assertIn("foto", hasil)

    def test_frame_base64_diubah_kembali_menjadi_byte(self):
        backend = GUIWebSocket("camera", camera=True)
        backend._terima_frame("/local_scope/vision/frame", {
            "jpeg": base64.b64encode(b"jpeg-tes").decode("ascii")
        })

        _state, frame, _status, _versi, versi_frame = backend.snapshot()

        self.assertEqual(frame, b"jpeg-tes")
        self.assertEqual(versi_frame, 1)


if __name__ == "__main__":
    unittest.main()
