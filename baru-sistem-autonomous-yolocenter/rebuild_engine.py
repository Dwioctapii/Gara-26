"""Bangun TensorRT engine pada Jetson target dan lakukan smoke test."""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys
import threading
import time

import numpy as np


# Jetson/aarch64 tidak menyediakan wheel PyPI onnxruntime-gpu biasa.
# TensorRT export tidak memerlukannya untuk menjalankan engine, jadi cegah
# Ultralytics membuang waktu mencoba pip install dua kali.
os.environ.setdefault("YOLO_AUTOINSTALL", "false")


if "bool" not in np.__dict__:
    np.bool = bool


def unique_sidecar(path: Path, label: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"{path.name}.{label}-{stamp}")
    sequence = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{label}-{stamp}-{sequence}")
        sequence += 1
    return candidate


def export_heartbeat(stop_event: threading.Event) -> None:
    """Berikan tanda hidup saat TensorRT builder tidak mencetak progres."""

    started = time.monotonic()
    while not stop_event.wait(20.0):
        elapsed = int(time.monotonic() - started)
        print(
            f"[EXPORT] TensorRT masih membangun engine... {elapsed} detik",
            flush=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export YOLO .pt menjadi TensorRT FP16 di perangkat ini"
    )
    parser.add_argument("model", nargs="?", default="best.pt")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument(
        "--workspace",
        type=float,
        default=1.0,
        help="workspace TensorRT dalam GiB (default 1.0, aman untuk Orin Nano 8GB)",
    )
    args = parser.parse_args()

    source = Path(args.model).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".pt":
        raise FileNotFoundError(f"model .pt tidak ditemukan: {source}")

    try:
        import torch
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("PyTorch Jetson dan ultralytics harus terpasang") from exc

    if not torch.cuda.is_available():
        raise RuntimeError("torch.cuda.is_available() = False")

    target = source.with_suffix(".engine")
    backup = None
    if target.exists():
        backup = unique_sidecar(target, "perangkat-lama")
        target.replace(backup)
        print(f"[EXPORT] Engine lama diamankan: {backup.name}")
    else:
        # Jika proses sebelumnya dihentikan sebelum blok TensorRT selesai,
        # target bisa hilang tetapi sidecar backup masih ada.
        old_backups = sorted(
            source.parent.glob(f"{target.name}.perangkat-lama-*"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        if old_backups:
            backup = old_backups[0]
            print(f"[EXPORT] Backup pemulihan ditemukan: {backup.name}")

    try:
        print(f"[EXPORT] GPU    : {torch.cuda.get_device_name(0)}")
        print(f"[EXPORT] Source : {source}")
        print(f"[EXPORT] Workspace: {args.workspace:.2f} GiB")
        print(
            "[EXPORT] Pembuatan TensorRT dapat tampak diam selama beberapa "
            "menit. Jangan tekan Ctrl+C.",
            flush=True,
        )
        progress_stop = threading.Event()
        progress_thread = threading.Thread(
            target=export_heartbeat,
            args=(progress_stop,),
            name="tensorrt-export-progress",
            daemon=True,
        )
        progress_thread.start()
        try:
            exported = YOLO(str(source)).export(
                format="engine",
                imgsz=args.imgsz,
                half=True,
                device=0,
                workspace=args.workspace,
            )
        finally:
            progress_stop.set()
            progress_thread.join(timeout=1.0)
        engine = Path(exported).expanduser().resolve()
        if not engine.is_file():
            raise RuntimeError(f"hasil export tidak ditemukan: {engine}")

        print(f"[TEST] Warm-up engine: {engine}")
        model = YOLO(str(engine), task="detect")
        dummy = np.zeros((args.imgsz, args.imgsz, 3), dtype=np.uint8)
        result = model.predict(
            source=dummy,
            imgsz=args.imgsz,
            device=0,
            verbose=False,
        )[0]
        print(f"[TEST] Berhasil; speed={getattr(result, 'speed', {})}")
        print(f"[DONE] Gunakan: ASV_MODEL_PATH={engine}")
        return 0
    except (Exception, KeyboardInterrupt):
        if target.exists():
            failed = unique_sidecar(target, "gagal")
            target.replace(failed)
            print(f"[RESTORE] Hasil gagal disimpan: {failed.name}", file=sys.stderr)
        if backup and backup.exists():
            backup.replace(target)
            print(f"[RESTORE] Engine lama dikembalikan: {target.name}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
