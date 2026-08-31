"""Menjalankan backend autonomous waypoint tanpa mengubah web client ZIP."""

import time

from config import *
from mavlink_worker import MavlinkWorker
from serial_worker import SerialWorker
from server import start_http, start_websocket
from state import store
from vision_worker import VisionWorker


def main() -> None:
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    mavlink = MavlinkWorker(MAVLINK_ENDPOINT, MAVLINK_BAUD, MISSION_REFRESH_SECONDS, store)
    mavlink.start()
    SerialWorker(TEENSY_PORT, TEENSY_BAUD, store).start()
    start_http(HTTP_HOST, HTTP_PORT, PHOTO_DIR, store)
    start_websocket(WS_HOST, WS_PORT, WS_HZ, store, mavlink.handle_command)
    VisionWorker(
        CAM_ATAS_SOURCE,
        CAM_BAWAH_SOURCE,
        MODEL_PATH,
        PHOTO_DIR,
        store,
    ).start()
    try:
        from gui import run_dashboard
        print("[GUI] Menjalankan Dashboard Matplotlib...")
        run_dashboard(store, PHOTO_DIR)
    except KeyboardInterrupt:
        pass
    finally:
        mavlink.stop()
        print("\n[ASV] stopped")


if __name__ == "__main__":
    main()
