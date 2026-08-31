#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
CAMERA_ID=""
SHOW_PREVIEW=0
NEO_PID=""

usage() {
    cat <<'EOF'
Penggunaan:
  bash start.sh                     Jalankan Neo saja
  bash start.sh --camera 4          Jalankan Neo + YOLO kamera 4
  bash start.sh --camera 4 --show   Sama, dengan preview OpenCV

Environment opsional:
  NEO_MAVLINK=/dev/serial/by-id/... Override port Pixhawk
  YOLO_MODEL=/path/model.engine      Override model TensorRT
  YOLO_PYTHON=/path/python3          Override Python untuk YOLO
EOF
}

while (($#)); do
    case "$1" in
        --camera)
            if (($# < 2)); then
                echo "[START] --camera membutuhkan nomor device" >&2
                exit 2
            fi
            CAMERA_ID="$2"
            shift 2
            ;;
        --show)
            SHOW_PREVIEW=1
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

if [[ -z "${NEO_MAVLINK:-}" ]]; then
    shopt -s nullglob
    PIXHAWK_PORTS=(/dev/serial/by-id/*Pixhawk*-if00)
    shopt -u nullglob

    if ((${#PIXHAWK_PORTS[@]} == 0)); then
        echo "[START] Pixhawk *-if00 tidak ditemukan di /dev/serial/by-id" >&2
        exit 1
    fi
    if ((${#PIXHAWK_PORTS[@]} > 1)); then
        echo "[START] Lebih dari satu Pixhawk ditemukan; set NEO_MAVLINK secara eksplisit:" >&2
        printf '  %s\n' "${PIXHAWK_PORTS[@]}" >&2
        exit 1
    fi
    NEO_MAVLINK="${PIXHAWK_PORTS[0]}"
fi

if [[ ! -e "${NEO_MAVLINK}" ]]; then
    echo "[START] Port tidak ditemukan: ${NEO_MAVLINK}" >&2
    exit 1
fi
if [[ ! -r "${NEO_MAVLINK}" || ! -w "${NEO_MAVLINK}" ]]; then
    echo "[START] Tidak punya izin baca/tulis: ${NEO_MAVLINK}" >&2
    echo "[START] Tambahkan user ke grup dialout lalu login ulang/reboot." >&2
    exit 1
fi

export NEO_MAVLINK
export NEO_MAVLINK_CONTROL_MODE="${NEO_MAVLINK_CONTROL_MODE:-velocity}"
export NEO_MAVLINK_REQUIRED_MODE="${NEO_MAVLINK_REQUIRED_MODE:-GUIDED}"
export NEO_AUTO_SET_GUIDED="${NEO_AUTO_SET_GUIDED:-1}"
export NEO_REQUIRE_ARMED="${NEO_REQUIRE_ARMED:-1}"
export NEO_AUTO_START="${NEO_AUTO_START:-0}"

if [[ -x "${SCRIPT_DIR}/.venv/bin/python3" ]]; then
    NEO_PYTHON="${SCRIPT_DIR}/.venv/bin/python3"
else
    NEO_PYTHON="$(command -v python3)"
fi

if ! "${NEO_PYTHON}" -c 'import pymavlink, websockets' 2>/dev/null; then
    echo "[START] Dependency Neo belum tersedia untuk ${NEO_PYTHON}" >&2
    echo "[START] Jalankan: python3 -m pip install -r ${SCRIPT_DIR}/requirements.txt" >&2
    exit 1
fi

echo "[START] Pixhawk : ${NEO_MAVLINK}"
echo "[START] Mode     : ${NEO_MAVLINK_REQUIRED_MODE}"
echo "[START] Auto arm : TIDAK"
echo "[START] Autonomy : ${NEO_AUTO_START} (aktifkan dengan: python3 neoctl.py enable)"

if [[ -z "${CAMERA_ID}" ]]; then
    cd -- "${SCRIPT_DIR}"
    exec "${NEO_PYTHON}" main.py
fi

cleanup() {
    if [[ -n "${NEO_PID}" ]] && kill -0 "${NEO_PID}" 2>/dev/null; then
        echo
        echo "[START] Menghentikan Neo..."
        kill -TERM "${NEO_PID}" 2>/dev/null || true
        wait "${NEO_PID}" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

cd -- "${SCRIPT_DIR}"
"${NEO_PYTHON}" main.py &
NEO_PID=$!

for _ in {1..40}; do
    if ! kill -0 "${NEO_PID}" 2>/dev/null; then
        wait "${NEO_PID}"
        exit 1
    fi
    if command -v curl >/dev/null && curl -fsS \
        http://127.0.0.1:8766/health >/dev/null 2>&1; then
        break
    fi
    sleep 0.25
done

YOLO_DIR="${REPO_DIR}/yolo8"
YOLO_MODEL="${YOLO_MODEL:-${YOLO_DIR}/best.engine}"
YOLO_PYTHON="${YOLO_PYTHON:-$(command -v python3)}"

if [[ ! -f "${YOLO_MODEL}" ]]; then
    echo "[START] Model YOLO tidak ditemukan: ${YOLO_MODEL}" >&2
    exit 1
fi

YOLO_ARGS=(
    "${YOLO_DIR}/run_pt_video.py"
    "${YOLO_MODEL}"
    "${CAMERA_ID}"
    --backend cuda
    --ws-url ws://127.0.0.1:8770
    --no-save
)
if ((SHOW_PREVIEW == 0)); then
    YOLO_ARGS+=(--no-show)
fi

echo "[START] Kamera   : ${CAMERA_ID}"
echo "[START] YOLO     : ${YOLO_MODEL}"
echo "[START] Ctrl+C menghentikan YOLO dan Neo"

cd -- "${YOLO_DIR}"
"${YOLO_PYTHON}" "${YOLO_ARGS[@]}"
