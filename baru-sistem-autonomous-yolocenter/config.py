"""Konfigurasi runtime. Semua nilai dapat dioverride lewat environment variable."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("ASV_DATA_DIR", ROOT / "data"))
PHOTO_DIR = DATA_DIR / "photos"
MODEL_PATH = Path(os.getenv("ASV_MODEL_PATH", ROOT / "best.engine"))


def _single_serial_by_id(pattern: str, fallback: str) -> str:
    matches = sorted(Path("/dev/serial/by-id").glob(pattern))
    return str(matches[0]) if len(matches) == 1 else fallback


def _camera_source(primary: str, legacy: str, default: str):
    value = os.getenv(primary, os.getenv(legacy, default)).strip()
    try:
        return int(value)
    except ValueError:
        return value


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in {
        "1", "true", "yes", "on"
    }

MAVLINK_ENDPOINT = os.getenv("ASV_MAVLINK") or _single_serial_by_id(
    "*Pixhawk*-if00", "/dev/ttyACM0"
)
MAVLINK_BAUD = int(os.getenv("ASV_MAVLINK_BAUD", "115200"))
MISSION_REFRESH_SECONDS = float(os.getenv("ASV_MISSION_REFRESH_SECONDS", "1.0"))

# Serial ke Teensy (servo + mode). Port bisa di-set setelah tahu device-nya:
#   export ASV_TEENSY_PORT=/dev/ttyUSB0   (paling umum)
#   export ASV_TEENSY_PORT=/dev/ttyACM1   (jika ACM0 sudah dipakai MAVLink)
# Cek port yang tersedia: ls /dev/tty* | grep -E "USB|ACM"
TEENSY_PORT = os.getenv("ASV_TEENSY_PORT") or _single_serial_by_id(
    "*Teensy*", "/dev/ttyACM2"
)
TEENSY_BAUD = int(os.getenv("ASV_TEENSY_BAUD", "115200"))

# 0.0.0.0 menerima koneksi dari seluruh perangkat LAN.
HTTP_HOST = os.getenv("ASV_HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("ASV_HTTP_PORT", "8766"))
WS_HOST = os.getenv("ASV_WS_HOST", "0.0.0.0")
WS_PORT = int(os.getenv("ASV_WS_PORT", "8765"))
WS_HZ = float(os.getenv("ASV_BROADCAST_HZ", "10"))

CAM_ATAS_SOURCE = _camera_source("ASV_CAM_ATAS", "ASV_CAM_ATAS_INDEX", "0")
CAM_BAWAH_SOURCE = _camera_source("ASV_CAM_BAWAH", "ASV_CAM_BAWAH_INDEX", "2")
CAMERA_WIDTH = int(os.getenv("ASV_CAMERA_WIDTH", "320"))
CAMERA_HEIGHT = int(os.getenv("ASV_CAMERA_HEIGHT", "240"))
CAMERA_FPS = float(os.getenv("ASV_CAMERA_FPS", "30"))

YOLO_IMGSZ = int(os.getenv("ASV_YOLO_IMGSZ", "640"))
YOLO_CONF = float(os.getenv("ASV_YOLO_CONF", "0.5"))
YOLO_DEVICE = os.getenv("ASV_YOLO_DEVICE", "0")
VISION_LOOP_DELAY_SECONDS = float(os.getenv("ASV_VISION_LOOP_DELAY_SECONDS", "0"))

# Matplotlib mahal bila seluruh dashboard digambar ulang 30+ kali/detik.
# Kamera diperbarui 15 FPS, sedangkan telemetry/peta cukup 5 Hz.
GUI_FPS = float(os.getenv("ASV_GUI_FPS", "15"))
GUI_TELEMETRY_HZ = float(os.getenv("ASV_GUI_TELEMETRY_HZ", "5"))
GUI_BLIT = _env_bool("ASV_GUI_BLIT", True)
GUI_TRACE_MAX_POINTS = int(os.getenv("ASV_GUI_TRACE_MAX_POINTS", "2000"))
GUI_CAMERA_STALE_SECONDS = float(
    os.getenv("ASV_GUI_CAMERA_STALE_SECONDS", "2.0")
)

# ─── BUOY-FOLLOWING CONFIG ────────────────────────────────────────────────────
# Dua titik yang mendefinisikan garis panduan oranye di frame kamera (320×240).
#   P1 = titik ATAS  garis  →  tengah atas   (160, 0)
#   P2 = titik BAWAH garis  →  tengah bawah  (160, 240)
# Ubah nilai ini via env var agar sesuai posisi kapal/kamera di lapangan:
#   export ASV_GUIDE_P1_X=160  ASV_GUIDE_P1_Y=0
#   export ASV_GUIDE_P2_X=160  ASV_GUIDE_P2_Y=240
GUIDE_LINE_P1 = (
    int(os.getenv("ASV_GUIDE_P1_X", str(CAMERA_WIDTH // 2))),
    int(os.getenv("ASV_GUIDE_P1_Y", "0")),
)
GUIDE_LINE_P2 = (
    int(os.getenv("ASV_GUIDE_P2_X", str(CAMERA_WIDTH // 2))),
    int(os.getenv("ASV_GUIDE_P2_Y", str(CAMERA_HEIGHT))),
)

# Servo kemudi: channel 1, PWM dalam µs
SERVO_STEER_CHANNEL = int(os.getenv("ASV_SERVO_STEER_CH", "1"))
SERVO_NEUTRAL       = int(os.getenv("ASV_SERVO_NEUTRAL",  "1500"))
SERVO_MIN           = int(os.getenv("ASV_SERVO_MIN",      "1100"))
SERVO_MAX           = int(os.getenv("ASV_SERVO_MAX",      "1900"))

# ── PID Gains ────────────────────────────────────────────────────────────────
# Kp : Proporsional — koreksi langsung terhadap error sekarang.
#       Naikan jika koreksi lambat, turunkan jika terlalu agresif / osilasi.
# Ki : Integral     — koreksi akumulasi error waktu lampau (hilangkan steady-state error).
#       Mulai dari 0, naikan perlahan jika kapal masih menyimpang meski error kecil.
# Kd : Derivatif    — koreksi laju perubahan error (damping / peredam osilasi).
#       Naikan jika osilasi, terlalu kecil bisa membuat respons lambat.
SERVO_KP = float(os.getenv("ASV_SERVO_KP", "2.0"))
SERVO_KI = float(os.getenv("ASV_SERVO_KI", "0.0"))
SERVO_KD = float(os.getenv("ASV_SERVO_KD", "0.0"))

# Anti-windup: batas maksimum akumulasi integral (dalam satuan pixel×detik).
# Mencegah integral "meledak" saat buoy tidak terdeteksi lama atau error besar.
SERVO_INTEGRAL_LIMIT = float(os.getenv("ASV_SERVO_INTEGRAL_LIMIT", "100.0"))

# Dead-band: error (pixel) yang dianggap "cukup lurus" → output = neutral.
# Mencegah servo bergetar terus saat kapal sudah hampir lurus.
SERVO_DEADBAND = float(os.getenv("ASV_SERVO_DEADBAND", "5.0"))

# Area minimum bounding box (px²) agar buoy merah dianggap sebagai target aktif.
# Resolusi kamera 320×240 → total 76 800 px². Default 500 px² menangkap buoy
# yang sudah cukup dekat tanpa terlalu sensitif terhadap objek jauh.
RED_BUOY_MIN_AREA   = int(os.getenv("ASV_RED_MIN_AREA",   "500"))
GREEN_BUOY_MIN_AREA = int(os.getenv("ASV_GREEN_MIN_AREA", "500"))

# PWM servo saat mode SEARCH (hanya satu buoy terdeteksi):
#   - Hanya buoyred  terdeteksi → belok KANAN (nilai > SERVO_NEUTRAL)
#   - Hanya buoygreen terdeteksi → belok KIRI  (nilai < SERVO_NEUTRAL)
# Offset dihitung dari SERVO_NEUTRAL (default ±200 µs).
SERVO_SEARCH_OFFSET = int(os.getenv("ASV_SERVO_SEARCH_OFFSET", "200"))
