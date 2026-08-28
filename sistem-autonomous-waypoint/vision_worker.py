"""Kamera atas/bawah dan capture foto berdasarkan deteksi YOLO PIS."""

import threading
import time

import cv2
import numpy as np

# Patch untuk bug kompatibilitas TensorRT dan versi NumPy terbaru
if not hasattr(np, 'bool'):
    np.bool = bool

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
        model = None
        if YOLO:
            if self.model_path.with_suffix('.engine').exists():
                model = YOLO(str(self.model_path.with_suffix('.engine')), task='detect')
                print("[VISION] Model YOLO (TensorRT .engine) berhasil dimuat.")
            elif self.model_path.with_suffix('.pt').exists():
                model = YOLO(str(self.model_path.with_suffix('.pt')))
                print("[VISION] Model YOLO (.pt) berhasil dimuat.")
                
        if not model:
            print("[VISION] YOLO/model tidak tersedia; kamera tetap berjalan tanpa deteksi.")
            
        top, bottom = cv2.VideoCapture(self.cam_atas), cv2.VideoCapture(self.cam_bawah)
        for camera in (top, bottom):
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        import numpy as np
        while True:
            ok_atas, frame_atas = top.read()
            ok_bawah, frame_bawah = bottom.read()
            
            # Jika salah satu kamera mati (atau index bergeser karena kabel terputus)
            if not ok_atas or not ok_bawah:
                err_img = np.zeros((240, 320, 3), dtype=np.uint8)
                cv2.putText(err_img, "ERROR: KAMERA TERPUTUS!", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                self.store.live_frame_bgr = err_img
                time.sleep(1.0)
                continue
                
            if model:
                # Pendeteksian YOLO HANYA menggunakan kamera atas (frame_atas)
                self._detect(model, frame_atas, frame_bawah)
            else:
                # Menampilkan layar peringatan jika model gagal dimuat
                err_img = np.zeros((240, 320, 3), dtype=np.uint8)
                cv2.putText(err_img, "ERROR: MODEL TIDAK TERSEDIA", (15, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
                self.store.live_frame_bgr = err_img
            time.sleep(0.03)

    def _detect(self, model, frame_atas, frame_bawah) -> None:
        snapshot = self.store.snapshot()["detection"]
        # TensorRT tidak memerlukan argumen device="cuda" karena sudah terkunci di memori GPU
        results = model(frame_atas, verbose=False, conf=0.5)
        
        # Simpan frame dengan anotasi (kotak YOLO) ke memori untuk dibaca oleh GUI
        self.store.live_frame_bgr = results[0].plot()

        for result in results:
            for box in result.boxes:
                name = model.names[int(box.cls[0])].lower()
                
                # Menghitung luasan bounding box (width * height) untuk estimasi jarak
                # box.xywh[0] mengembalikan tensor [x_center, y_center, width, height]
                w, h = box.xywh[0][2].item(), box.xywh[0][3].item()
                bbox_area = w * h
                
                # Threshold luasan minimal agar dianggap "dekat" (sesuaikan nilainya)
                # Resolusi kamera diset 320x240, jadi total area adalah 76.800
                MIN_AREA_THRESHOLD = 5000 
                
                # Jika box terlalu kecil (objek masih jauh), abaikan deteksi ini
                if bbox_area < MIN_AREA_THRESHOLD:
                    continue

                if "blue" in name and not snapshot["foto_bawah_ready"]:
                    # Mengambil gambar kamera bawah yang sudah di-standby (agar gambarnya real-time)
                    img_to_save = frame_bawah if frame_bawah is not None else frame_atas
                    cv2.imwrite(str(self.photo_dir / "bawah.jpg"), img_to_save)
                    self.store.update({"detection": {"label": "BOXBLUE (LOCKED & SAVED)", "foto_bawah_ready": True}})
                    return
                if "green" in name and not snapshot["foto_atas_ready"]:
                    cv2.imwrite(str(self.photo_dir / "atas.jpg"), frame_atas)
                    self.store.update({"detection": {"label": "BOXGREEN (LOCKED & SAVED)", "foto_atas_ready": True}})
                    return
