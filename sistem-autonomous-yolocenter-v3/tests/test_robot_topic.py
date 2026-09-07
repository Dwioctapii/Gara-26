import importlib.util
import os
import socket
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path


WEBSOCKETS_TERSEDIA = importlib.util.find_spec("websockets") is not None


@unittest.skipUnless(WEBSOCKETS_TERSEDIA, "websockets belum terpasang")
class RobotTopicTest(unittest.TestCase):
    def test_publish_subscribe_dan_retained(self):
        from mod03_robot_topic import RobotTopicClient

        with socket.socket() as pencari_port:
            pencari_port.bind(("127.0.0.1", 0))
            port = pencari_port.getsockname()[1]

        lingkungan = os.environ.copy()
        lingkungan["ASV_BROKER_HOST"] = "127.0.0.1"
        lingkungan["ASV_BROKER_PORT"] = str(port)
        root = Path(__file__).resolve().parents[1]
        broker = subprocess.Popen(
            [sys.executable, str(root / "mod02_local_websocket_manager.py")],
            cwd=root,
            env=lingkungan,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        penerbit = RobotTopicClient(f"ws://127.0.0.1:{port}")
        pelanggan = RobotTopicClient(f"ws://127.0.0.1:{port}")
        pelanggan_terlambat = RobotTopicClient(f"ws://127.0.0.1:{port}")
        diterima = []
        diterima_terlambat = []
        sinyal = threading.Event()
        sinyal_terlambat = threading.Event()

        try:
            pelanggan.berlangganan("/tes", lambda _topik, data: (diterima.append(data), sinyal.set()))
            pelanggan.mulai()
            penerbit.mulai()
            self.assertTrue(pelanggan.tunggu_terhubung(5))
            self.assertTrue(penerbit.tunggu_terhubung(5))
            penerbit.publikasi("/tes", {"nilai": 42})
            self.assertTrue(sinyal.wait(5))
            self.assertEqual(diterima[-1], {"nilai": 42})

            pelanggan_terlambat.berlangganan(
                "/tes",
                lambda _topik, data: (diterima_terlambat.append(data), sinyal_terlambat.set()),
            )
            pelanggan_terlambat.mulai()
            self.assertTrue(sinyal_terlambat.wait(5))
            self.assertEqual(diterima_terlambat[-1], {"nilai": 42})
        finally:
            penerbit.berhenti()
            pelanggan.berhenti()
            pelanggan_terlambat.berhenti()
            broker.terminate()
            broker.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
