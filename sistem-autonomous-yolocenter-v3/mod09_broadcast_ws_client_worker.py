"""Penggabung hot topic dan cold state untuk backend GUI."""

from __future__ import annotations

import copy
import logging
import threading
import time
from typing import Any

import mod01_config as config
from mod03_robot_topic import (
    TOPIK_ARENA,
    TOPIK_GUI_STATE,
    TOPIK_MAVLINK,
    TOPIK_PERINTAH,
    TOPIK_SERIAL,
    TOPIK_VISION,
    robot_topic,
)
from mod04_state_content import DEFAULT_HOT_DATA
from mod05_state_manager import state


pencatat = logging.getLogger("GuiStateWorker")


def _gabungkan(target: dict[str, Any], perubahan: dict[str, Any]) -> None:
    for kunci, nilai in perubahan.items():
        if isinstance(nilai, dict) and isinstance(target.get(kunci), dict):
            _gabungkan(target[kunci], nilai)
        else:
            target[kunci] = copy.deepcopy(nilai)


class GuiStateWorker:
    """Menyusun snapshot kompatibel frontend dari beberapa hot topic."""

    def __init__(self) -> None:
        self.data_panas = copy.deepcopy(DEFAULT_HOT_DATA)
        self.kunci = threading.RLock()
        self.data_dingin = state.baca()
        self.waktu_ubah_dingin = state.jalur.stat().st_mtime_ns

    def mulai(self) -> None:
        for topik in (TOPIK_MAVLINK, TOPIK_VISION, TOPIK_SERIAL, TOPIK_ARENA):
            robot_topic.berlangganan(topik, self._terima_data_panas)
        robot_topic.berlangganan(TOPIK_PERINTAH, self._terima_perintah)
        robot_topic.mulai()

    def _terima_data_panas(self, _topik: str, data: Any) -> None:
        if isinstance(data, dict):
            with self.kunci:
                _gabungkan(self.data_panas, data)

    def _terima_perintah(self, _topik: str, perintah: Any) -> None:
        if not isinstance(perintah, dict):
            return
        try:
            if perintah.get("command") == "set_home" and not perintah.get("home"):
                with self.kunci:
                    gps = self.data_panas["gps"]
                    perintah = {**perintah, "home": {"lat": gps["lat"], "lon": gps["lon"]}}
            state.terapkan_perintah(perintah)
            if perintah.get("command") == "reset_mission":
                with self.kunci:
                    _gabungkan(self.data_panas, {"missionState": "IDLE", "mission": {"current": 0}})
            if perintah.get("command") == "calibration":
                with self.kunci:
                    _gabungkan(self.data_panas, {"gps": {"lastCalib": time.strftime("%F %T")}})
            if perintah.get("command") == "reset_photo":
                for kamera in ("atas", "bawah"):
                    (config.PHOTO_DIR / f"{kamera}.jpg").unlink(missing_ok=True)
                    state.atur_status_foto(kamera, False)
        except Exception as galat:
            pencatat.error("Perintah cold state gagal: %s", galat)

    def snapshot(self) -> dict[str, Any]:
        with self.kunci:
            hasil = copy.deepcopy(self.data_panas)
        waktu_ubah = state.jalur.stat().st_mtime_ns
        if waktu_ubah != self.waktu_ubah_dingin:
            self.data_dingin = state.baca()
            self.waktu_ubah_dingin = waktu_ubah
        data_dingin = copy.deepcopy(self.data_dingin)
        _gabungkan(hasil, data_dingin)
        hasil["detection"]["foto_atas_ready"] = data_dingin["foto"]["atas"]["tersedia"]
        hasil["detection"]["foto_bawah_ready"] = data_dingin["foto"]["bawah"]["tersedia"]
        gps = hasil["gps"]
        posisi = hasil["position"]
        hasil.update(
            lat=gps["lat"],
            lon=gps["lon"],
            sog=gps["sog"],
            cog=gps["cog"],
            kompas=gps["cog"],
            x=posisi["x"],
            y=posisi["y"],
        )
        hasil["mission"]["waypoints"] = data_dingin["mission"]["waypoints"]
        hasil["mission"]["total"] = len(hasil["mission"]["waypoints"])
        hasil["timestamp"] = time.time()
        return hasil

    def jalankan(self) -> None:
        self.mulai()
        jeda = 1.0 / max(1.0, config.WS_HZ)
        while True:
            robot_topic.publikasi(TOPIK_GUI_STATE, self.snapshot())
            time.sleep(jeda)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    GuiStateWorker().jalankan()


if __name__ == "__main__":
    main()
