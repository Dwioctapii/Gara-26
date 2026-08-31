"""Backend Ultralytics CUDA/TensorRT untuk NVIDIA Jetson dan GPU NVIDIA."""

from __future__ import annotations

from pathlib import Path
import time

import numpy as np

# TensorRT Python lama (umum pada JetPack 5) masih membaca ``np.bool`` saat
# memetakan dtype binding. Alias itu dihapus pada NumPy 1.24. Gunakan __dict__
# agar pengecekan tidak memicu FutureWarning milik NumPy.
if "bool" not in np.__dict__:
    np.bool = np.bool_


def _as_numpy(value):
    """Konversi tensor Ultralytics lama/baru tanpa bergantung pada versinya."""

    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        return value.numpy()
    return np.asarray(value)


def _class_name(names, class_id: int) -> str:
    if isinstance(names, dict):
        return str(names.get(class_id, class_id))
    if isinstance(names, (list, tuple)) and 0 <= class_id < len(names):
        return str(names[class_id])
    return str(class_id)


class YOLOCuda:
    """Adapter dengan kontrak ``predict`` yang sama seperti YOLODirectML.

    File ``.pt`` dijalankan melalui PyTorch CUDA. File ``.engine`` dijalankan
    melalui TensorRT. Engine TensorRT wajib dibuat pada Jetson target karena
    engine bergantung pada GPU dan versi TensorRT/CUDA perangkat tersebut.
    """

    def __init__(
        self,
        model_path: str | Path,
        imgsz: int = 640,
        conf: float = 0.25,
        iou: float = 0.45,
        cpu: bool = False,
        force_export: bool = False,
    ) -> None:
        try:
            import torch
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError(
                "Backend CUDA memerlukan PyTorch Jetson dan Ultralytics. "
                "Ikuti JETSON.md; jangan memasang onnxruntime-directml."
            ) from exc

        source_path = Path(model_path).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Model tidak ditemukan: {source_path}")
        if source_path.suffix.lower() not in {".pt", ".engine"}:
            raise ValueError("Backend CUDA menerima model .pt atau .engine")

        self.imgsz = imgsz
        self.conf = conf
        self.iou = iou
        self.cpu = cpu
        self.device = "cpu" if cpu else "cuda:0"

        if not cpu and not torch.cuda.is_available():
            raise RuntimeError(
                "torch.cuda.is_available() = False. Periksa JetPack dan wheel "
                "PyTorch yang cocok dengan versi JetPack."
            )

        if force_export:
            if cpu:
                raise ValueError("Export TensorRT tidak dapat memakai --cpu")
            if source_path.suffix.lower() != ".pt":
                raise ValueError("--force-export membutuhkan sumber model .pt")
            print(f"[CUDA] Export TensorRT FP16 di perangkat ini: {source_path.name}")
            exporter = YOLO(str(source_path))
            exported = exporter.export(
                format="engine",
                imgsz=imgsz,
                half=True,
                device=0,
                workspace=2,
            )
            source_path = Path(exported).resolve()
            if not source_path.is_file():
                raise RuntimeError(f"Hasil export TensorRT tidak ada: {source_path}")

        self.model_path = source_path
        self.is_tensorrt = source_path.suffix.lower() == ".engine"
        self.model = YOLO(str(source_path), task="detect")
        # Jangan membaca self.model.names di sini. Pada sejumlah Ultralytics
        # bawaan Jetson, model TensorRT masih disimpan sebagai string path
        # sampai predict pertama sehingga property names melempar:
        #     'str' object has no attribute 'names'
        self.names = {}

        backend = "TensorRT" if self.is_tensorrt else "PyTorch CUDA"
        if cpu:
            backend = "PyTorch CPU"
        print(f"[CUDA] Backend : {backend}")
        print(f"[CUDA] Model   : {source_path}")
        if not cpu:
            print(f"[CUDA] Device  : {torch.cuda.get_device_name(0)}")

        # Warm-up sekaligus memvalidasi bahwa model dan CUDA/TensorRT kompatibel.
        dummy = np.zeros((imgsz, imgsz, 3), dtype=np.uint8)
        warmup_result = self._run(dummy)
        self.names = getattr(warmup_result, "names", None) or {}
        print("[CUDA] Ready.")

    def _run(self, frame: np.ndarray):
        kwargs = {
            "source": frame,
            "imgsz": self.imgsz,
            "conf": self.conf,
            "iou": self.iou,
            "device": self.device,
            "verbose": False,
        }
        # TensorRT menentukan precision dari engine. ``half`` hanya relevan
        # untuk model PyTorch dan tidak dipakai pada fallback CPU.
        if not self.is_tensorrt and not self.cpu:
            kwargs["half"] = True
        return self.model.predict(**kwargs)[0]

    def predict(self, frame: np.ndarray) -> tuple[list[dict], float]:
        started = time.perf_counter()
        result = self._run(frame)
        wall_ms = (time.perf_counter() - started) * 1000.0
        speed = getattr(result, "speed", None) or {}
        inference_ms = float(speed.get("inference", wall_ms))

        detections: list[dict] = []
        boxes = result.boxes
        if boxes is None:
            return detections, inference_ms

        xyxy = _as_numpy(boxes.xyxy)
        confidences = _as_numpy(boxes.conf)
        class_ids = _as_numpy(boxes.cls).astype(int)
        names = getattr(result, "names", None) or self.names

        for box, confidence, class_id in zip(xyxy, confidences, class_ids):
            detections.append(
                {
                    "box": box.astype(np.float32, copy=False),
                    "score": float(confidence),
                    "class_id": int(class_id),
                    "class_name": _class_name(names, int(class_id)),
                }
            )

        return detections, inference_ms
