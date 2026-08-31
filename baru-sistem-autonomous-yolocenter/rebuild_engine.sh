#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${ASV_PYTHON:-$(command -v python3)}"
export YOLO_AUTOINSTALL=false

cd -- "${SCRIPT_DIR}"
exec "${PYTHON_BIN}" rebuild_engine.py "$@"
