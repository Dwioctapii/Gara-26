"""Launcher empat proses GUI yang sinkron melalui WebSocket."""

import multiprocessing as mp
import time

from .arena import run as run_arena
from .camera import run as run_camera
from .controls import run as run_controls
from .debug import run as run_debug


def run_dashboard(_store=None, _photo_dir=None):
    context = mp.get_context("spawn")
    stop_event = context.Event()
    processes = [
        context.Process(target=run_debug, args=(stop_event,), name="gui-debug"),
        context.Process(target=run_controls, args=(stop_event,), name="gui-controls"),
        context.Process(target=run_arena, args=(stop_event,), name="gui-arena"),
        context.Process(target=run_camera, args=(stop_event,), name="gui-camera"),
    ]
    for process in processes:
        process.start()
    print("[GUI] 4 proses aktif: " + ", ".join(f"{p.name}=PID {p.pid}" for p in processes))

    try:
        while not stop_event.is_set():
            if any(not process.is_alive() for process in processes):
                stop_event.set()
            time.sleep(0.2)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        for process in processes:
            process.join(timeout=2)
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join()


__all__ = ["run_dashboard"]
