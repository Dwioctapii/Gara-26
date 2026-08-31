#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CAM_ATAS="${ASV_CAM_ATAS:-0}"
CAM_BAWAH="${ASV_CAM_BAWAH:-2}"
REBUILD=0

usage() {
    cat <<'EOF'
Penggunaan:
  bash start.sh --atas 4 --bawah 6
  bash start.sh --atas 4 --bawah 6 --rebuild-engine

Gunakan `v4l2-ctl --list-devices` untuk menentukan kamera atas/bawah.
Port Pixhawk dan Teensy dicari otomatis dari /dev/serial/by-id.
EOF
}

while (($#)); do
    case "$1" in
        --atas)
            CAM_ATAS="$2"
            shift 2
            ;;
        --bawah)
            CAM_BAWAH="$2"
            shift 2
            ;;
        --rebuild-engine)
            REBUILD=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "[START] Argumen tidak dikenal: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

single_port() {
    local pattern="$1"
    local label="$2"
    local matches=()
    shopt -s nullglob
    matches=(/dev/serial/by-id/$pattern)
    shopt -u nullglob
    if ((${#matches[@]} != 1)); then
        echo "[START] ${label}: ditemukan ${#matches[@]} port untuk pola ${pattern}" >&2
        printf '  %s\n' "${matches[@]}" >&2
        exit 1
    fi
    printf '%s' "${matches[0]}"
}

ASV_MAVLINK="${ASV_MAVLINK:-$(single_port '*Pixhawk*-if00' Pixhawk)}"
ASV_TEENSY_PORT="${ASV_TEENSY_PORT:-$(single_port '*Teensy*' Teensy)}"
export ASV_MAVLINK ASV_TEENSY_PORT
export ASV_CAM_ATAS="${CAM_ATAS}"
export ASV_CAM_BAWAH="${CAM_BAWAH}"

for port in "${ASV_MAVLINK}" "${ASV_TEENSY_PORT}"; do
    if [[ ! -r "${port}" || ! -w "${port}" ]]; then
        echo "[START] Tidak punya izin baca/tulis: ${port}" >&2
        echo "[START] Tambahkan user ke grup dialout lalu login ulang/reboot." >&2
        exit 1
    fi
done

if [[ -n "${ASV_PYTHON:-}" ]]; then
    PYTHON_BIN="${ASV_PYTHON}"
elif [[ -x "${SCRIPT_DIR}/.venv/bin/python3" ]] && \
     "${SCRIPT_DIR}/.venv/bin/python3" -c \
       'import cv2, numpy, pymavlink, ultralytics, websockets' 2>/dev/null; then
    PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python3"
else
    PYTHON_BIN="$(command -v python3)"
fi
export ASV_PYTHON="${PYTHON_BIN}"

if ! "${PYTHON_BIN}" -c \
    'import cv2, numpy, pymavlink, ultralytics, websockets' 2>/dev/null; then
    echo "[START] Dependency belum lengkap untuk ${PYTHON_BIN}" >&2
    exit 1
fi

cd -- "${SCRIPT_DIR}"
if ((REBUILD)); then
    "${PYTHON_BIN}" rebuild_engine.py best.pt
fi

echo "[START] Pixhawk     : ${ASV_MAVLINK}"
echo "[START] Teensy      : ${ASV_TEENSY_PORT}"
echo "[START] Kamera atas : ${ASV_CAM_ATAS}"
echo "[START] Kamera bawah: ${ASV_CAM_BAWAH}"
echo "[START] Model       : ${ASV_MODEL_PATH:-${SCRIPT_DIR}/best.engine}"
echo "[START] GUI         : ${ASV_GUI_FPS:-15} FPS, telemetry ${ASV_GUI_TELEMETRY_HZ:-5} Hz"

exec "${PYTHON_BIN}" main.py
