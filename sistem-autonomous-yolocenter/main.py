"""Menjalankan backend autonomous waypoint tanpa mengubah web client ZIP."""

import atexit
import time
from pathlib import Path

from config import *
from http_worker import start_http
from mavlink_worker import MavlinkWorker
from mqtt_worker import JembatanMqtt
from serial_worker import SerialWorker
from state import store
from vision_worker import VisionWorker
from websocket_worker import start_websocket


def main() -> None:
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)

    # ── Muat konfigurasi dari state.json (PID, track, home, loggerActive) ──
    state_path = DATA_DIR / "state.json"
    store.load_config(state_path)

    # ── Simpan konfigurasi saat program berhenti ──────────────────────────
    def save_on_exit():
        store.save_config(state_path)
        print("[MAIN] Konfigurasi disimpan ke", state_path)
    atexit.register(save_on_exit)

    mavlink = MavlinkWorker(MAVLINK_ENDPOINT, MAVLINK_BAUD, MISSION_REFRESH_SECONDS, store)
    mavlink.start()
    SerialWorker(TEENSY_PORT, TEENSY_BAUD, store).start()

    # ── Combined command handler ────────────────────────────────────────────
    # Menangani reset_photo (hapus file fisik) + delegate ke mavlink untuk lainnya.
    def command_handler(cmd: dict) -> dict:
        if cmd.get("command") == "reset_photo":
            deleted = []
            for fname in ("atas.jpg", "bawah.jpg"):
                path = PHOTO_DIR / fname
                try:
                    if path.exists():
                        path.unlink()
                        deleted.append(fname)
                except Exception as exc:
                    print(f"[CMD] Gagal hapus {fname}: {exc}")
            print(f"[CMD] reset_photo: {deleted if deleted else 'tidak ada file'}")
            return {"deleted": deleted}
        return mavlink.handle_command(cmd)

    start_http(HTTP_HOST, HTTP_PORT, store, command_handler)
    start_websocket(WS_HOST, WS_PORT, WS_HZ, store, PHOTO_DIR, command_handler)

    # MQTT worker: broadcast foto + state ke cloud (tanpa config.txt)
    mqtt_bridge = JembatanMqtt(PHOTO_DIR, store)
    mqtt_bridge.start()

    VisionWorker(CAM_ATAS_INDEX, CAM_BAWAH_INDEX, MODEL_PATH, PHOTO_DIR, store).start()

    try:
        from gui import run_dashboard
        print("[GUI] Menjalankan 4 komponen GUI via WebSocket...")
        run_dashboard(store, PHOTO_DIR)
    except KeyboardInterrupt:
        pass
    finally:
        mqtt_bridge.stop()
        mavlink.stop()
        print("\n[ASV] stopped")


if __name__ == "__main__":
    main()