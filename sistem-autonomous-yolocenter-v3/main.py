"""CLI supervisor; hanya mengurutkan, memantau, dan menghentikan proses."""

from __future__ import annotations

import argparse
import os
import py_compile
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import mod01_config as config


ROOT = Path(__file__).resolve().parent


def pilih_python_runtime() -> Path:
    kandidat = [
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
    ]
    for python_runtime in kandidat:
        if python_runtime.is_file():
            return python_runtime
    return Path(sys.executable)


PYTHON_RUNTIME = pilih_python_runtime()

PROSES_UTAMA = [
    ("broker", "mod02_local_websocket_manager.py"),
    ("gui-state", "mod09_broadcast_ws_client_worker.py"),
    ("mavlink", "mod07_mavlink_worker.py"),
    ("arena", "mod102_arena_worker.py"),
    ("serial", "mod06_serial_worker.py"),
    ("vision", "mod08_vision_worker.py"),
    ("http", "mod11_http_worker.py"),
    ("client-http", "../client/server_client.py"),
]


@dataclass
class ManagedProcess:
    nama: str
    sumber: str
    perintah: list[str]
    proses: subprocess.Popen | None = None
    jumlah_restart: int = 0


class ProcessSupervisor:
    """Mengelola proses, satu kali restart, dan penghentian process group."""

    def __init__(self) -> None:
        self.proses: list[ManagedProcess] = []
        self.sudah_berhenti = False

    def mulai_berkas(self, nama: str, berkas: str) -> None:
        spesifikasi = ManagedProcess(
            nama=nama,
            sumber=berkas,
            perintah=[str(PYTHON_RUNTIME), "-u", str(ROOT / berkas)],
        )
        self.proses.append(spesifikasi)
        self._mulai_proses(spesifikasi)

    def mulai_modul(self, nama: str, modul: str) -> None:
        spesifikasi = ManagedProcess(
            nama=nama,
            sumber=f"{modul}/__main__.py",
            perintah=[str(PYTHON_RUNTIME), "-u", "-m", modul],
        )
        self.proses.append(spesifikasi)
        self._mulai_proses(spesifikasi)

    def _mulai_proses(self, spesifikasi: ManagedProcess) -> None:
        opsi_grup = {}
        if os.name == "nt":
            opsi_grup["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            opsi_grup["start_new_session"] = True

        proses = subprocess.Popen(
            spesifikasi.perintah,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **opsi_grup,
        )
        spesifikasi.proses = proses
        threading.Thread(
            target=self._teruskan_output,
            args=(spesifikasi.sumber, proses),
            daemon=True,
            name=f"stdout-{spesifikasi.nama}-{spesifikasi.jumlah_restart}",
        ).start()

    @staticmethod
    def _teruskan_output(sumber: str, proses: subprocess.Popen) -> None:
        if proses.stdout is None:
            return
        for baris in proses.stdout:
            print(f"[STDOUT : {sumber}] {baris.rstrip()}", flush=True)

    def pantau(self) -> None:
        while True:
            for spesifikasi in self.proses:
                proses = spesifikasi.proses
                if proses is None:
                    continue
                kode = proses.poll()
                if kode is None:
                    continue
                if spesifikasi.jumlah_restart == 0:
                    spesifikasi.jumlah_restart = 1
                    print(
                        f"[STDOUT : main.py] RETRY 1/1 proses {spesifikasi.nama} "
                        f"setelah berhenti dengan kode {kode}",
                        flush=True,
                    )
                    self._hentikan_proses(spesifikasi, paksa=True)
                    time.sleep(0.5)
                    self._mulai_proses(spesifikasi)
                    continue
                raise RuntimeError(
                    f"proses {spesifikasi.nama} berhenti lagi dengan kode {kode}; "
                    "batas retry habis"
                )
            time.sleep(0.2)

    def berhenti(self) -> None:
        if self.sudah_berhenti:
            return
        self.sudah_berhenti = True
        print("[STDOUT : main.py] Menutup seluruh worker", flush=True)

        for spesifikasi in reversed(self.proses):
            self._hentikan_proses(spesifikasi, paksa=False)

        batas_waktu = time.monotonic() + 3
        while time.monotonic() < batas_waktu:
            if all(
                item.proses is None or item.proses.poll() is not None
                for item in self.proses
            ):
                break
            time.sleep(0.05)

        for spesifikasi in reversed(self.proses):
            proses = spesifikasi.proses
            if proses is not None and proses.poll() is None:
                print(
                    f"[STDOUT : main.py] KILL proses {spesifikasi.nama}",
                    flush=True,
                )
                self._hentikan_proses(spesifikasi, paksa=True)

        for spesifikasi in reversed(self.proses):
            proses = spesifikasi.proses
            if proses is None:
                continue
            try:
                proses.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proses.kill()
                proses.wait()

    @staticmethod
    def _hentikan_proses(spesifikasi: ManagedProcess, paksa: bool) -> None:
        proses = spesifikasi.proses
        if proses is None:
            return

        if os.name == "nt":
            if paksa:
                subprocess.run(
                    ["taskkill", "/PID", str(proses.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            elif proses.poll() is None:
                proses.terminate()
            return

        sinyal = signal.SIGKILL if paksa else signal.SIGTERM
        try:
            os.killpg(proses.pid, sinyal)
        except ProcessLookupError:
            pass


def periksa_sintaks() -> int:
    berkas_python = sorted(ROOT.glob("mod*.py")) + sorted((ROOT / "gui").glob("*.py"))
    berkas_python.extend([
        ROOT / "main.py",
        ROOT.parent / "client" / "server_client.py",
    ])
    gagal = []
    for berkas in berkas_python:
        try:
            py_compile.compile(str(berkas), doraise=True)
        except py_compile.PyCompileError as galat:
            gagal.append(f"{berkas.name}: {galat}")
    if gagal:
        print("\n".join(gagal))
        return 1
    pemeriksaan_dependency = subprocess.run(
        [
            str(PYTHON_RUNTIME),
            "-c",
            "import cv2, numpy, paho.mqtt.client, pymavlink, serial, ultralytics, websockets",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if pemeriksaan_dependency.returncode:
        print("Dependency belum lengkap:")
        print(pemeriksaan_dependency.stderr.strip())
        return 1
    print(f"Sintaks valid: {len(berkas_python)} berkas")
    print(f"Dependency valid: {PYTHON_RUNTIME}")
    return 0


def jalankan(tanpa_gui: bool, aktifkan_mqtt: bool) -> int:
    pengawas = ProcessSupervisor()
    try:
        pengawas.mulai_berkas(*PROSES_UTAMA[0])
        time.sleep(0.5)
        for spesifikasi in PROSES_UTAMA[1:]:
            pengawas.mulai_berkas(*spesifikasi)
        if aktifkan_mqtt:
            print(
                f"[STDOUT : main.py] MQTT broadcast aktif -> "
                f"{config.MQTT_HOST}:{config.MQTT_PORT}",
                flush=True,
            )
            pengawas.mulai_berkas("mqtt", "mod10_broadcast_mqtt_worker.py")
        else:
            print("[STDOUT : main.py] MQTT broadcast nonaktif", flush=True)
        if not tanpa_gui:
            pengawas.mulai_modul("gui", "gui")
        print("[STDOUT : main.py] Semua proses dimulai dan sedang dipantau", flush=True)
        pengawas.pantau()
    except KeyboardInterrupt:
        print("[STDOUT : main.py] Penghentian diminta", flush=True)
        return 0
    except Exception as galat:
        print(f"[STDOUT : main.py] GALAT {galat}", flush=True)
        return 1
    finally:
        pengawas.berhenti()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Supervisor sistem autonomous YOLOCenter")
    parser.add_argument("--check", action="store_true", help="periksa seluruh sintaks")
    parser.add_argument("--tanpa-gui", action="store_true", help="jalankan backend tanpa jendela GUI")
    pilihan_mqtt = parser.add_mutually_exclusive_group()
    pilihan_mqtt.add_argument(
        "--mqtt",
        dest="aktifkan_mqtt",
        action="store_true",
        help="aktifkan bridge MQTT cloud",
    )
    pilihan_mqtt.add_argument(
        "--tanpa-mqtt",
        dest="aktifkan_mqtt",
        action="store_false",
        help="jalankan tanpa bridge MQTT cloud",
    )
    parser.set_defaults(aktifkan_mqtt=config.MQTT_ENABLED)
    argumen = parser.parse_args()
    if argumen.check:
        return periksa_sintaks()
    return jalankan(argumen.tanpa_gui, argumen.aktifkan_mqtt)


if __name__ == "__main__":
    raise SystemExit(main())
