"""Konfigurasi runtime. Semua nilai dapat dioverride lewat environment variable."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("ASV_DATA_DIR", ROOT / "data"))
PHOTO_DIR = DATA_DIR / "photos"
MODEL_PATH = Path(os.getenv("ASV_MODEL_PATH", ROOT / "best.pt"))

MAVLINK_ENDPOINT = os.getenv("ASV_MAVLINK", "/dev/ttyACM0")
MAVLINK_BAUD = int(os.getenv("ASV_MAVLINK_BAUD", "115200"))
MISSION_REFRESH_SECONDS = float(os.getenv("ASV_MISSION_REFRESH_SECONDS", "5.0"))
MISSION_ITEM_TIMEOUT = float(os.getenv("ASV_MISSION_ITEM_TIMEOUT", "1.0"))
MISSION_MAX_RETRIES = int(os.getenv("ASV_MISSION_MAX_RETRIES", "4"))
WAYPOINT_REACHED_RADIUS = float(os.getenv("ASV_WAYPOINT_REACHED_RADIUS", "1.5"))

# 0.0.0.0 menerima koneksi dari seluruh perangkat LAN.
HTTP_HOST = os.getenv("ASV_HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("ASV_HTTP_PORT", "8766"))
WS_HOST = os.getenv("ASV_WS_HOST", "0.0.0.0")
WS_PORT = int(os.getenv("ASV_WS_PORT", "8765"))
WS_HZ = float(os.getenv("ASV_BROADCAST_HZ", "10"))

CAM_ATAS_INDEX = int(os.getenv("ASV_CAM_ATAS_INDEX", "0"))
CAM_BAWAH_INDEX = int(os.getenv("ASV_CAM_BAWAH_INDEX", "1"))
