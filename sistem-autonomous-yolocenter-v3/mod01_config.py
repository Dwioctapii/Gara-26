"""Konfigurasi runtime. Semua nilai dapat dioverride lewat environment variable."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("ASV_DATA_DIR", ROOT / "data"))
PHOTO_DIR = DATA_DIR / "photos"
STATE_PATH = Path(os.getenv("ASV_STATE_PATH", DATA_DIR / "state.json"))
MODEL_PATH = Path(os.getenv("ASV_MODEL_PATH", ROOT / "best.engine"))

YOLO_DEVICE = os.getenv("ASV_YOLO_DEVICE", "0").strip()
YOLO_CONFIDENCE = float(os.getenv("ASV_YOLO_CONFIDENCE", "0.5"))
YOLO_IMAGE_SIZE = 640
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
BOX_PHOTO_MIN_AREA = int(os.getenv("ASV_BOX_PHOTO_MIN_AREA", "20000"))
BOX_MAX_HEIGHT_RATIO = float(os.getenv("ASV_BOX_MAX_HEIGHT_RATIO", "1.2"))
LIVE_FRAME_JPEG_QUALITY = int(os.getenv("ASV_LIVE_FRAME_JPEG_QUALITY", "75"))

MAVLINK_ENDPOINT = os.getenv("ASV_MAVLINK", "/dev/ttyACM1")
MAVLINK_BAUD = int(os.getenv("ASV_MAVLINK_BAUD", "115200"))
MISSION_REFRESH_SECONDS = float(os.getenv("ASV_MISSION_REFRESH_SECONDS", "1.0"))

# Serial ke Teensy (servo + mode). Port bisa di-set setelah tahu device-nya:
#   export ASV_TEENSY_PORT=/dev/ttyUSB0   (paling umum)
#   export ASV_TEENSY_PORT=/dev/ttyACM1   (jika ACM0 sudah dipakai MAVLink)
# Cek port yang tersedia: ls /dev/tty* | grep -E "USB|ACM"
TEENSY_PORT = os.getenv("ASV_TEENSY_PORT", "/dev/ttyACM0")
TEENSY_BAUD = int(os.getenv("ASV_TEENSY_BAUD", "115200"))

# 0.0.0.0 menerima koneksi dari seluruh perangkat LAN.
HTTP_HOST = os.getenv("ASV_HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("ASV_HTTP_PORT", "8766"))
BROKER_HOST = os.getenv("ASV_BROKER_HOST", "0.0.0.0")
BROKER_PORT = int(os.getenv("ASV_BROKER_PORT", "8765"))
BROKER_CLIENT_HOST = os.getenv("ASV_BROKER_CLIENT_HOST", "127.0.0.1")
BROKER_URL = os.getenv("ASV_BROKER_URL", f"ws://{BROKER_CLIENT_HOST}:{BROKER_PORT}")
WS_HOST = BROKER_HOST
WS_PORT = BROKER_PORT
WS_HZ = float(os.getenv("ASV_BROADCAST_HZ", "10"))

MQTT_HOST = os.getenv(
    "ASV_MQTT_HOST",
    "b786a44b5790491898b3c676180e7862.s1.eu.hivemq.cloud",
)
MQTT_PORT = int(os.getenv("ASV_MQTT_PORT", "8883"))
MQTT_USER = os.getenv("ASV_MQTT_USER", "noxindocraft")
MQTT_PASS = os.getenv("ASV_MQTT_PASS", "Zancraft1&")
MQTT_ENABLED = os.getenv("ASV_ENABLE_MQTT", "1") == "1"

CAM_ATAS_INDEX = int(os.getenv("ASV_CAM_ATAS_INDEX", "0"))
CAM_BAWAH_INDEX = int(os.getenv("ASV_CAM_BAWAH_INDEX", "2"))

# ─── BUOY-FOLLOWING CONFIG ────────────────────────────────────────────────────
# Dua titik yang mendefinisikan garis panduan oranye di frame kamera (640×480).
#   P1 = titik ATAS  garis  →  tengah atas   (320, 0)
#   P2 = titik BAWAH garis  →  tengah bawah  (320, 480)
# Ubah nilai ini via env var agar sesuai posisi kapal/kamera di lapangan:
#   export ASV_GUIDE_P1_X=320  ASV_GUIDE_P1_Y=0
#   export ASV_GUIDE_P2_X=320  ASV_GUIDE_P2_Y=480
GUIDE_LINE_P1 = (
    int(os.getenv("ASV_GUIDE_P1_X", "320")),
    int(os.getenv("ASV_GUIDE_P1_Y", "0")),
)
GUIDE_LINE_P2 = (
    int(os.getenv("ASV_GUIDE_P2_X", "320")),
    int(os.getenv("ASV_GUIDE_P2_Y", "480")),
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
# Resolusi kamera 640×480. Ambang lama 200 px² pada 320×240 diskalakan 4×
# agar jarak fisik pemicu tetap mendekati perilaku sebelumnya.
RED_BUOY_MIN_AREA   = int(os.getenv("ASV_RED_MIN_AREA",   "800"))
GREEN_BUOY_MIN_AREA = int(os.getenv("ASV_GREEN_MIN_AREA", "800"))

# PWM servo saat mode SEARCH (hanya satu buoy terdeteksi):
#   - Hanya buoyred  terdeteksi → belok KANAN (nilai > SERVO_NEUTRAL)
#   - Hanya buoygreen terdeteksi → belok KIRI  (nilai < SERVO_NEUTRAL)
# Offset dihitung dari SERVO_NEUTRAL (default ±200 µs).
SERVO_SEARCH_OFFSET = int(os.getenv("ASV_SERVO_SEARCH_OFFSET", "200"))

# ─── Catatan ──────────────────────────────────────────────────────────────────
# Nilai MQTT bawaan berada di file ini. Environment ASV_MQTT_* hanya override.
