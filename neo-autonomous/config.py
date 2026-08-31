"""Konfigurasi Neo Autonomous; seluruh nilai dapat dioverride lewat env."""

from __future__ import annotations

import os
from pathlib import Path


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }



def default_mavlink_endpoint() -> str:
    """Pilih satu Pixhawk USB stabil; fallback dipakai di non-Linux/test."""

    candidates = sorted(Path("/dev/serial/by-id").glob("*Pixhawk*-if00"))
    if len(candidates) == 1:
        return str(candidates[0])
    return "/dev/ttyACM0"


MAVLINK_ENDPOINT = os.getenv("NEO_MAVLINK") or default_mavlink_endpoint()
MAVLINK_BAUD = int(os.getenv("NEO_MAVLINK_BAUD", "115200"))
MAVLINK_CONTROL_MODE = os.getenv("NEO_MAVLINK_CONTROL_MODE", "velocity").lower()
MAVLINK_REQUIRED_MODE = os.getenv("NEO_MAVLINK_REQUIRED_MODE", "GUIDED").upper()
MAVLINK_HEARTBEAT_TIMEOUT_SECONDS = float(
    os.getenv("NEO_MAVLINK_HEARTBEAT_TIMEOUT_SECONDS", "3.0")
)
MAVLINK_HEARTBEAT_HZ = float(os.getenv("NEO_MAVLINK_HEARTBEAT_HZ", "1.0"))

HTTP_HOST = os.getenv("NEO_HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("NEO_HTTP_PORT", "8766"))
TELEMETRY_WS_HOST = os.getenv("NEO_TELEMETRY_WS_HOST", "0.0.0.0")
TELEMETRY_WS_PORT = int(os.getenv("NEO_TELEMETRY_WS_PORT", "8765"))
TELEMETRY_HZ = float(os.getenv("NEO_TELEMETRY_HZ", "10"))

# YOLOv8 mengirim ke port khusus ini agar koneksinya tidak dibanjiri telemetry.
TARGET_WS_HOST = os.getenv("NEO_TARGET_WS_HOST", "0.0.0.0")
TARGET_WS_PORT = int(os.getenv("NEO_TARGET_WS_PORT", "8770"))

AUTO_START = env_bool("NEO_AUTO_START", False)
REQUIRE_ARMED = env_bool("NEO_REQUIRE_ARMED", True)
ENABLE_REMOTE_MAVLINK_COMMANDS = env_bool("NEO_ENABLE_REMOTE_COMMANDS", False)
AUTO_SET_GUIDED = env_bool("NEO_AUTO_SET_GUIDED", False)

CONTROL_HZ = float(os.getenv("NEO_CONTROL_HZ", "10"))
TARGET_TIMEOUT_SECONDS = float(os.getenv("NEO_TARGET_TIMEOUT_SECONDS", "0.6"))
STOP_DISTANCE_M = float(os.getenv("NEO_STOP_DISTANCE_M", "2.0"))
DISTANCE_KP = float(os.getenv("NEO_DISTANCE_KP", "0.45"))
MAX_FORWARD_MPS = float(os.getenv("NEO_MAX_FORWARD_MPS", "1.5"))
HEADING_KP = float(os.getenv("NEO_HEADING_KP", "1.2"))
MAX_YAW_RATE_RPS = float(os.getenv("NEO_MAX_YAW_RATE_RPS", "0.7"))
BEARING_DEADBAND_DEGREES = float(
    os.getenv("NEO_BEARING_DEADBAND_DEGREES", "2.0")
)
DRIVE_BEARING_LIMIT_DEGREES = float(
    os.getenv("NEO_DRIVE_BEARING_LIMIT_DEGREES", "55.0")
)

if MAVLINK_CONTROL_MODE not in {"velocity", "manual"}:
    raise ValueError("NEO_MAVLINK_CONTROL_MODE harus velocity atau manual")
if not MAVLINK_REQUIRED_MODE:
    raise ValueError("NEO_MAVLINK_REQUIRED_MODE tidak boleh kosong")
if MAVLINK_HEARTBEAT_TIMEOUT_SECONDS <= 0 or MAVLINK_HEARTBEAT_HZ <= 0:
    raise ValueError("timeout dan frekuensi heartbeat MAVLink harus positif")
if TARGET_TIMEOUT_SECONDS <= 0 or CONTROL_HZ <= 0:
    raise ValueError("timeout dan control Hz harus lebih besar dari nol")
if STOP_DISTANCE_M < 0 or MAX_FORWARD_MPS <= 0 or MAX_YAW_RATE_RPS <= 0:
    raise ValueError("batas jarak/kecepatan konfigurasi tidak valid")
if DISTANCE_KP < 0 or HEADING_KP < 0:
    raise ValueError("gain kontrol tidak boleh negatif")
if not 0 < DRIVE_BEARING_LIMIT_DEGREES <= 180:
    raise ValueError("batas bearing untuk maju harus di antara 0 dan 180")
