"""Menjalankan backend autonomous waypoint tanpa mengubah web client ZIP."""

import time

from config import *
from mavlink_worker import MavlinkWorker
from server import start_http, start_websocket
from state import store
from vision_worker import VisionWorker


def main() -> None:
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    mavlink = MavlinkWorker(MAVLINK_ENDPOINT, MAVLINK_BAUD, MISSION_REFRESH_SECONDS,
                            store, MISSION_ITEM_TIMEOUT, MISSION_MAX_RETRIES,
                            WAYPOINT_REACHED_RADIUS)
    mavlink.start()
    start_http(HTTP_HOST, HTTP_PORT, PHOTO_DIR, store)
    start_websocket(WS_HOST, WS_PORT, WS_HZ, store)
    VisionWorker(CAM_ATAS_INDEX, CAM_BAWAH_INDEX, MODEL_PATH, PHOTO_DIR, store).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        mavlink.stop()
        print("\n[ASV] stopped")


if __name__ == "__main__":
    main()
