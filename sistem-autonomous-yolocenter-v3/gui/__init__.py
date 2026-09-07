"""Launcher proses GUI lama dengan backend RobotTopic baru."""

import multiprocessing as mp
import time

from .camera import run as jalankan_kamera
from .controls import run as jalankan_kontrol
from .debug import run as jalankan_debug


def run_dashboard(_store=None, _photo_dir=None):
    konteks = mp.get_context("spawn")
    sinyal_berhenti = konteks.Event()
    proses = [
        konteks.Process(target=jalankan_debug, args=(sinyal_berhenti,), name="gui-debug"),
        konteks.Process(target=jalankan_kontrol, args=(sinyal_berhenti,), name="gui-controls"),
        konteks.Process(target=jalankan_kamera, args=(sinyal_berhenti,), name="gui-camera"),
    ]
    for proses_gui in proses:
        proses_gui.start()
    print("[GUI] Aktif: " + ", ".join(f"{item.name}=PID {item.pid}" for item in proses))

    try:
        while not sinyal_berhenti.is_set():
            if any(not item.is_alive() for item in proses):
                sinyal_berhenti.set()
            time.sleep(0.2)
    except KeyboardInterrupt:
        sinyal_berhenti.set()
    finally:
        for proses_gui in proses:
            proses_gui.join(timeout=2)
            if proses_gui.is_alive():
                proses_gui.terminate()
                proses_gui.join()


__all__ = ["run_dashboard"]
