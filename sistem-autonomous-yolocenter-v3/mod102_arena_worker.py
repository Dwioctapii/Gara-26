"""Pemetaan arena yang dikunci otomatis saat misi MAVLink dimulai."""

from __future__ import annotations

import copy
import logging
import math
import threading
import time
from collections import deque
from typing import Any

from mod03_robot_topic import TOPIK_ARENA, TOPIK_MAVLINK, TOPIK_PERINTAH, robot_topic
from mod05_state_manager import state
from mod101_virtual_gps_mapper import VirtualGPSMapper


pencatat = logging.getLogger("ArenaWorker")
INTERVAL_PUBLIKASI = 0.2
JARAK_MINIMUM_RIWAYAT = 0.10
BATAS_RIWAYAT = 2000


def _gabungkan(target: dict[str, Any], perubahan: dict[str, Any]) -> None:
    for kunci, nilai in perubahan.items():
        if isinstance(nilai, dict) and isinstance(target.get(kunci), dict):
            _gabungkan(target[kunci], nilai)
        else:
            target[kunci] = copy.deepcopy(nilai)


class ArenaWorker:
    """Mengunci mapper dari MAVLink dan menerbitkan satu JSON arena lengkap."""

    def __init__(self, penyimpan=state, topik=robot_topic) -> None:
        self.penyimpan = penyimpan
        self.topik = topik
        self.kunci = threading.RLock()
        self.data_mavlink: dict[str, Any] = {}
        self.data_cold: dict[str, Any] = {}
        self.mapper = None
        self.acuan_aktif = None
        self.posisi_sekarang = None
        self.riwayat = deque(maxlen=BATAS_RIWAYAT)
        self.status_operasi = "berhenti"
        self.galat = None
        self.waktu_baca_cold = 0.0

    def mulai(self) -> None:
        self.topik.berlangganan(TOPIK_MAVLINK, self._terima_mavlink)
        self.topik.berlangganan(TOPIK_PERINTAH, self._terima_perintah)
        self.topik.mulai()
        self._jalankan()

    def _terima_mavlink(self, _topik: str, perubahan: Any) -> None:
        if not isinstance(perubahan, dict):
            return
        with self.kunci:
            _gabungkan(self.data_mavlink, perubahan)

    def _terima_perintah(self, _topik: str, perintah: Any) -> None:
        if not isinstance(perintah, dict) or perintah.get("command") != "clear_history":
            return
        with self.kunci:
            self.riwayat.clear()

    @staticmethod
    def _heading_derajat(mavlink: dict[str, Any]) -> float:
        gps = mavlink.get("gps", {})
        if gps.get("heading") is not None:
            return float(gps["heading"]) % 360.0
        orientasi = mavlink.get("orientation", {})
        if orientasi.get("z") is not None:
            return math.degrees(float(orientasi["z"])) % 360.0
        return float(gps.get("cog", 0.0)) % 360.0

    @staticmethod
    def _baca_status_operasi(mavlink: dict[str, Any]) -> str:
        if mavlink.get("connected") is False:
            return "jeda"

        status_arm = str(mavlink.get("arm", "")).lower()
        if status_arm == "disarmed":
            return "berhenti"

        status = str(
            mavlink.get("missionState")
            or mavlink.get("mission", {}).get("state")
            or ""
        ).upper()
        if status in {"RUNNING", "ACTIVE"}:
            return "berjalan"
        if status in {"PAUSED", "HOLDING"}:
            return "jeda"
        if status in {"IDLE", "STOPPED", "COMPLETED", "COMPLETE"}:
            return "berhenti"

        bersenjata = status_arm == "armed"
        mode = str(mavlink.get("mode", "")).upper()
        if bersenjata and mode == "AUTO":
            return "berjalan"
        if bersenjata:
            return "jeda"
        return "berhenti"

    def _pasang_mapper(self, acuan: dict[str, Any] | None) -> None:
        self.acuan_aktif = copy.deepcopy(acuan)
        if acuan is None:
            self.mapper = None
            self.posisi_sekarang = None
            return
        self.mapper = VirtualGPSMapper(
            (float(acuan["x"]), float(acuan["y"])),
            (float(acuan["lat"]), float(acuan["lon"])),
            float(acuan["heading"]),
        )

    def _sinkron_cold(self) -> None:
        sekarang = time.monotonic()
        if sekarang - self.waktu_baca_cold < 0.5 and self.data_cold:
            return
        data = self.penyimpan.baca()
        acuan = data["arena"].get("posisi_acuan")
        with self.kunci:
            self.data_cold = data
            if acuan != self.acuan_aktif:
                self._pasang_mapper(acuan)
                self.riwayat.clear()
        self.waktu_baca_cold = sekarang

    def _kunci_dari_mavlink(self, mavlink: dict[str, Any]) -> None:
        gps = mavlink.get("gps", {})
        if not gps.get("fix") or gps.get("lat") is None or gps.get("lon") is None:
            raise ValueError("misi aktif, tetapi GPS belum fix")

        nama_arena = self.data_cold.get("currentTrack", "A")
        arena_aktif = self.data_cold["arena"].get(nama_arena)
        if not isinstance(arena_aktif, dict):
            raise ValueError(f"arena {nama_arena} tidak tersedia")
        titik_mulai = arena_aktif.get("titik_mulai")
        if not isinstance(titik_mulai, dict):
            raise ValueError(f"titik mulai arena {nama_arena} tidak tersedia")

        acuan = {
            "x": float(titik_mulai["x"]),
            "y": float(titik_mulai["y"]),
            "lat": float(gps["lat"]),
            "lon": float(gps["lon"]),
            "heading": self._heading_derajat(mavlink),
            "timestamp": time.time(),
            "arena": nama_arena,
        }
        data = self.penyimpan.atur_kunci_arena(True, acuan)
        with self.kunci:
            self.data_cold = data
            self._pasang_mapper(acuan)
            self.riwayat.clear()
            self.galat = None
        pencatat.info("Acuan arena %s dikunci dari awal misi MAVLink", nama_arena)

    def _sinkron_status_misi(self) -> None:
        with self.kunci:
            mavlink = copy.deepcopy(self.data_mavlink)
            arena_cold = copy.deepcopy(self.data_cold.get("arena", {}))
        status = self._baca_status_operasi(mavlink)
        terkunci = bool(arena_cold.get("acuan_terkunci"))

        with self.kunci:
            self.status_operasi = status

        if status == "berjalan" and (not terkunci or self.mapper is None):
            try:
                self._kunci_dari_mavlink(mavlink)
            except (KeyError, TypeError, ValueError) as galat:
                with self.kunci:
                    self.galat = str(galat)
                pencatat.warning("Acuan arena belum dapat dikunci: %s", galat)
            return

        if status == "berhenti" and terkunci:
            data = self.penyimpan.atur_kunci_arena(False)
            with self.kunci:
                self.data_cold = data
            pencatat.info("Sesi arena selesai; acuan dibuka untuk misi berikutnya")

    def _perbarui_posisi(self) -> None:
        with self.kunci:
            mavlink = copy.deepcopy(self.data_mavlink)
            mapper = self.mapper
            rekam = self.status_operasi == "berjalan"
        if mapper is None:
            return
        gps = mavlink.get("gps", {})
        if not gps.get("fix") or gps.get("lat") is None or gps.get("lon") is None:
            return

        lat = float(gps["lat"])
        lon = float(gps["lon"])
        x, y = mapper.gps_to_virtual(lat, lon)
        posisi = {
            "x": round(x, 3),
            "y": round(y, 3),
            "lat": lat,
            "lon": lon,
            "heading": round(self._heading_derajat(mavlink), 2),
            "timestamp": time.time(),
        }
        with self.kunci:
            self.posisi_sekarang = posisi
            if rekam and (
                not self.riwayat
                or self._jarak(self.riwayat[-1], posisi) >= JARAK_MINIMUM_RIWAYAT
            ):
                self.riwayat.append(copy.deepcopy(posisi))

    @staticmethod
    def _jarak(titik_awal: dict[str, Any], titik_akhir: dict[str, Any]) -> float:
        return math.hypot(
            titik_akhir["x"] - titik_awal["x"],
            titik_akhir["y"] - titik_awal["y"],
        )

    def snapshot(self) -> dict[str, Any]:
        with self.kunci:
            arena = copy.deepcopy(self.data_cold.get("arena", {}))
            arena.update({
                "aktif": self.data_cold.get("currentTrack", "A"),
                "dimulai": bool(arena.get("acuan_terkunci")),
                "berjalan": self.status_operasi == "berjalan",
                "status": self.status_operasi,
                "posisi_sekarang": copy.deepcopy(self.posisi_sekarang),
                "riwayat_pergerakan": list(copy.deepcopy(self.riwayat)),
                "galat": self.galat,
            })
        return {"arena": arena}

    def _jalankan(self) -> None:
        while True:
            self._sinkron_cold()
            self._sinkron_status_misi()
            self._perbarui_posisi()
            self.topik.publikasi(TOPIK_ARENA, self.snapshot())
            time.sleep(INTERVAL_PUBLIKASI)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ArenaWorker().mulai()


if __name__ == "__main__":
    main()
