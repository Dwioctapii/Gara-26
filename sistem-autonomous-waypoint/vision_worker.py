"""Kamera atas/bawah dan capture foto berdasarkan deteksi YOLO PIS."""

import threading
import time

import cv2

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None


class VisionWorker:
    def __init__(self, cam_atas: int, cam_bawah: int, model_path, photo_dir, store) -> None:
        self.cam_atas, self.cam_bawah = cam_atas, cam_bawah
        self.model_path, self.photo_dir, self.store = model_path, photo_dir, store

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="vision").start()

    def _run(self) -> None:
        model = YOLO(str(self.model_path)) if YOLO and self.model_path.exists() else None
        if model is None:
            print("[VISION] YOLO/model tidak tersedia; layanan foto menunggu model.")
        top, bottom = cv2.VideoCapture(self.cam_atas), cv2.VideoCapture(self.cam_bawah)
        for camera in (top, bottom):
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        while True:
            ok, frame = top.read()
            if not ok:
                time.sleep(0.1)
                continue
            if model:
                self._detect(model, frame, bottom)
            time.sleep(0.03)

    def _detect(self, model, frame_atas, camera_bawah) -> None:
        snapshot = self.store.snapshot()["detection"]
        for result in model(frame_atas, verbose=False, conf=0.5):
            for box in result.boxes:
                name = model.names[int(box.cls[0])].lower()
                if "blue" in name and not snapshot["foto_bawah_ready"]:
                    ok, frame_bawah = camera_bawah.read()
                    cv2.imwrite(str(self.photo_dir / "bawah.jpg"), frame_bawah if ok else frame_atas)
                    self.store.update({"detection": {"label": "BOXBLUE (LOCKED & SAVED)", "foto_bawah_ready": True}})
                    return
                if "green" in name and not snapshot["foto_atas_ready"]:
                    cv2.imwrite(str(self.photo_dir / "atas.jpg"), frame_atas)
                    self.store.update({"detection": {"label": "BOXGREEN (LOCKED & SAVED)", "foto_atas_ready": True}})
                    return
