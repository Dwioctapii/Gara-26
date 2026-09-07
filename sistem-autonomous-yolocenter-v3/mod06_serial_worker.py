"""Worker serial Teensy; sumber data selalu berasal dari hot topic."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

try:
    import serial
except ImportError:
    serial = None

import mod01_config as config
from mod03_robot_topic import TOPIK_MAVLINK, TOPIK_SERIAL, TOPIK_VISION, robot_topic


pencatat = logging.getLogger("SerialWorker")

PETA_MODE = {
    "MANUAL": 0x00,
    "AUTO": 0x01,
    "HOLD": 0x02,
    "LOITER": 0x02,
    "GUIDED": 0x02,
    "RTL": 0x02,
    "STABILIZE": 0x00,
}
PETA_DETEKSI = {"NONE": 0, "BOTH": 1, "RED_ONLY": 2, "GREEN_ONLY": 3}


def buat_paket(pwm: int, mode: int, deteksi: int) -> bytes:
    pwm = max(config.SERVO_MIN, min(config.SERVO_MAX, int(pwm)))
    rendah = pwm & 0xFF
    tinggi = pwm >> 8
    checksum = rendah ^ tinggi ^ mode ^ deteksi
    return bytes((0xAA, rendah, tinggi, mode, deteksi, checksum))


class SerialWorker:
    """Mengirim kendali terbaru ke Teensy dengan heartbeat 100 ms."""

    def __init__(self, port: str, baud: int) -> None:
        self.port = port
        self.baud = baud
        self.data_mavlink: dict[str, Any] = {}
        self.data_vision: dict[str, Any] = {}
        self.sinyal_berhenti = threading.Event()

    def mulai(self) -> None:
        robot_topic.berlangganan(TOPIK_MAVLINK, self._terima_mavlink)
        robot_topic.berlangganan(TOPIK_VISION, self._terima_vision)
        robot_topic.mulai()
        self._jalankan()

    def _terima_mavlink(self, _topik: str, data: Any) -> None:
        if isinstance(data, dict):
            self.data_mavlink.update(data)

    def _terima_vision(self, _topik: str, data: Any) -> None:
        if isinstance(data, dict):
            self.data_vision.update(data)

    def _status(self, perubahan: dict[str, Any]) -> None:
        robot_topic.publikasi(TOPIK_SERIAL, {"serial": perubahan})

    def _jalankan(self) -> None:
        if serial is None:
            raise RuntimeError("pyserial belum terpasang")

        koneksi = None
        while not self.sinyal_berhenti.is_set():
            try:
                if koneksi is None or not koneksi.is_open:
                    koneksi = serial.Serial(self.port, self.baud, timeout=0)
                    pencatat.info("Terhubung ke %s @ %s", self.port, self.baud)

                buoy = self.data_vision.get("buoy", {})
                pwm = int(buoy.get("servo_pwm", config.SERVO_NEUTRAL))
                nama_mode = str(self.data_mavlink.get("mode", "DISCONNECTED")).upper()
                nama_deteksi = str(buoy.get("mode", "NONE")).upper()
                mode = PETA_MODE.get(nama_mode, 0xFF)
                deteksi = PETA_DETEKSI.get(nama_deteksi, 0)
                koneksi.write(buat_paket(pwm, mode, deteksi))
                self._status({
                    "connected": True,
                    "port": self.port,
                    "error": None,
                    "last_pwm": pwm,
                    "last_mode": nama_mode,
                    "last_mode_b": mode,
                })
                time.sleep(0.1)
            except Exception as galat:
                self._status({"connected": False, "port": self.port, "error": str(galat)})
                pencatat.warning("Koneksi serial gagal: %s", galat)
                if koneksi:
                    try:
                        koneksi.close()
                    except Exception:
                        pass
                koneksi = None
                time.sleep(2)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    SerialWorker(config.TEENSY_PORT, config.TEENSY_BAUD).mulai()


if __name__ == "__main__":
    main()
