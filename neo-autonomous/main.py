"""Entry point Neo Autonomous."""

from __future__ import annotations

import signal
import threading

import config
from controller import AutonomyController
from mavlink_worker import MavlinkWorker
from servers import start_http, start_target_websocket, start_telemetry_websocket
from state import StateStore


def main() -> None:
    store = StateStore(auto_start=config.AUTO_START)
    mavlink = MavlinkWorker(config, store)
    controller = AutonomyController(config, store, mavlink)
    stopped = threading.Event()

    def request_stop(*_args) -> None:
        stopped.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    mavlink.start()
    controller.start()
    start_http(config.HTTP_HOST, config.HTTP_PORT, store)
    start_telemetry_websocket(
        config.TELEMETRY_WS_HOST,
        config.TELEMETRY_WS_PORT,
        config.TELEMETRY_HZ,
        store,
        mavlink.handle_command,
    )
    start_target_websocket(config.TARGET_WS_HOST, config.TARGET_WS_PORT, store)

    print("[NEO] Siap. Kontrol autonomy:", "ON" if config.AUTO_START else "OFF")
    try:
        stopped.wait()
    finally:
        controller.stop()
        mavlink.stop()
        print("[NEO] stopped")


if __name__ == "__main__":
    main()

