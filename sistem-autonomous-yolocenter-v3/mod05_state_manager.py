"""Cold state bersama yang langsung terhubung ke JSON dan file lock."""

from __future__ import annotations

import copy
import json
import math
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import mod01_config as config
from mod04_state_content import DEFAULT_CONFIG


def _gabungkan(target: dict[str, Any], perubahan: dict[str, Any]) -> None:
    for kunci, nilai in perubahan.items():
        if isinstance(nilai, dict) and isinstance(target.get(kunci), dict):
            _gabungkan(target[kunci], nilai)
        else:
            target[kunci] = copy.deepcopy(nilai)


class StateManager:
    """Membaca dan menulis cold state secara aman lintas proses."""

    def __init__(self, jalur: str | Path | None = None) -> None:
        self.jalur = Path(jalur or config.STATE_PATH)
        self.jalur_kunci = self.jalur.with_suffix(self.jalur.suffix + ".lock")
        self.jalur.parent.mkdir(parents=True, exist_ok=True)
        if not self.jalur.exists():
            with self._kunci_file():
                if not self.jalur.exists():
                    self._tulis_tanpa_kunci(copy.deepcopy(DEFAULT_CONFIG))

    @contextmanager
    def _kunci_file(self, batas_waktu: float = 5.0) -> Iterator[None]:
        token = f"{os.getpid()}:{uuid.uuid4().hex}"
        mulai = time.monotonic()
        while True:
            try:
                deskriptor = os.open(self.jalur_kunci, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(deskriptor, "w", encoding="utf-8") as berkas:
                    berkas.write(token)
                break
            except FileExistsError:
                try:
                    if time.time() - self.jalur_kunci.stat().st_mtime > 30:
                        self.jalur_kunci.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() - mulai >= batas_waktu:
                    raise TimeoutError(f"cold state masih dikunci: {self.jalur_kunci}")
                time.sleep(0.02)

        try:
            yield
        finally:
            try:
                if self.jalur_kunci.read_text(encoding="utf-8") == token:
                    self.jalur_kunci.unlink(missing_ok=True)
            except FileNotFoundError:
                pass

    def baca(self) -> dict[str, Any]:
        with self._kunci_file():
            return self._baca_tanpa_kunci()

    def perbarui(self, perubahan: dict[str, Any]) -> dict[str, Any]:
        with self._kunci_file():
            data = self._baca_tanpa_kunci()
            _gabungkan(data, perubahan)
            self._tulis_tanpa_kunci(data)
            return copy.deepcopy(data)

    def ganti_misi(self, daftar_waypoint: list[dict[str, Any]]) -> dict[str, Any]:
        return self.perbarui({"mission": {"waypoints": daftar_waypoint}})

    def atur_kunci_arena(
        self,
        terkunci: bool,
        posisi: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ubah kunci sesi arena dan posisi acuan secara atomik."""
        perubahan: dict[str, Any] = {"acuan_terkunci": bool(terkunci)}
        if posisi is None:
            return self.perbarui({"arena": perubahan})

        wajib = ("x", "y", "lat", "lon", "heading")
        hasil = {}
        for kunci in wajib:
            nilai = float(posisi[kunci])
            if not math.isfinite(nilai):
                raise ValueError(f"posisi acuan {kunci} tidak valid")
            hasil[kunci] = nilai
        hasil["timestamp"] = float(posisi.get("timestamp", time.time()))
        hasil["arena"] = str(posisi.get("arena", "A"))
        perubahan["posisi_acuan"] = hasil
        return self.perbarui({"arena": perubahan})

    def status_foto(self) -> dict[str, Any]:
        return self.baca()["foto"]

    def atur_tahan_foto(self, ditahan: bool) -> dict[str, Any]:
        return self.perbarui({"tahan_foto": bool(ditahan)})

    def atur_status_foto(self, kamera: str, tersedia: bool) -> dict[str, Any]:
        if kamera not in {"atas", "bawah"}:
            raise ValueError(f"kamera tidak dikenal: {kamera}")

        with self._kunci_file():
            data = self._baca_tanpa_kunci()
            status = data["foto"][kamera]
            tersedia = bool(tersedia)
            if status["tersedia"] != tersedia:
                status["tersedia"] = tersedia
                status["revisi"] = int(status.get("revisi", 0)) + 1
                self._tulis_tanpa_kunci(data)
            return copy.deepcopy(data["foto"])

    def reset_status_foto(self) -> dict[str, Any]:
        with self._kunci_file():
            data = self._baca_tanpa_kunci()
            berubah = False
            for kamera in ("atas", "bawah"):
                status = data["foto"][kamera]
                if status["tersedia"]:
                    status["tersedia"] = False
                    status["revisi"] = int(status.get("revisi", 0)) + 1
                    berubah = True
            if berubah:
                self._tulis_tanpa_kunci(data)
            return copy.deepcopy(data["foto"])

    def terapkan_perintah(self, perintah: dict[str, Any]) -> dict[str, Any]:
        nama = perintah.get("command")
        perubahan: dict[str, Any] = {}

        if nama == "set_pid":
            batas = {
                "kp": (-1000.0, 1000.0),
                "ki": (-1000.0, 1000.0),
                "kd": (-1000.0, 1000.0),
                "deadband": (0.0, 1000.0),
                "integral_limit": (0.0, 1_000_000.0),
            }
            pid = self.baca()["pid_config"]
            for kunci, (minimum, maksimum) in batas.items():
                nilai = float(perintah[kunci])
                if not math.isfinite(nilai) or not minimum <= nilai <= maksimum:
                    raise ValueError(f"PID {kunci} di luar batas")
                pid[kunci] = nilai
            pid["_version"] = int(pid.get("_version", 0)) + 1
            perubahan["pid_config"] = pid
        elif nama == "set_track" and perintah.get("track") in {"A", "B", "C", "D"}:
            perubahan["currentTrack"] = perintah["track"]
        elif nama == "set_home":
            home = perintah.get("home")
            if not isinstance(home, dict) or home.get("lat") is None or home.get("lon") is None:
                raise ValueError("GPS belum valid untuk menyimpan home")
            perubahan["home"] = {"lat": float(home["lat"]), "lon": float(home["lon"])}
        elif nama == "logger" and perintah.get("action") in {"start", "stop"}:
            perubahan["loggerActive"] = perintah["action"] == "start"

        return self.perbarui(perubahan) if perubahan else self.baca()

    def pid_snapshot(self) -> dict[str, Any]:
        return self.baca()["pid_config"]

    def snapshot(self) -> dict[str, Any]:
        return self.baca()

    def update(self, perubahan: dict[str, Any]) -> dict[str, Any]:
        return self.perbarui(perubahan)

    def replace_mission(self, daftar_waypoint: list[dict[str, Any]]) -> dict[str, Any]:
        return self.ganti_misi(daftar_waypoint)

    def command(self, perintah: dict[str, Any]) -> dict[str, Any]:
        return self.terapkan_perintah(perintah)

    def _baca_tanpa_kunci(self) -> dict[str, Any]:
        data = copy.deepcopy(DEFAULT_CONFIG)
        if self.jalur.exists():
            try:
                tersimpan = json.loads(self.jalur.read_text(encoding="utf-8"))
                if isinstance(tersimpan, dict):
                    _gabungkan(data, tersimpan)
            except (OSError, json.JSONDecodeError) as galat:
                raise RuntimeError(f"cold state rusak: {galat}") from galat
        return data

    def _tulis(self, data: dict[str, Any]) -> None:
        with self._kunci_file():
            self._tulis_tanpa_kunci(data)

    def _tulis_tanpa_kunci(self, data: dict[str, Any]) -> None:
        sementara = self.jalur.with_name(f".{self.jalur.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            sementara.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(sementara, self.jalur)
        finally:
            sementara.unlink(missing_ok=True)


state = StateManager()
store = state
