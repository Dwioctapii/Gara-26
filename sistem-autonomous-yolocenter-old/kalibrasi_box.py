"""Script untuk kalibrasi Threshold Area (Pixel) Kamera Atas."""

import cv2
import time
import numpy as np

# Patch bug TensorRT & Numpy
if not hasattr(np, 'bool'):
    np.bool = bool

from ultralytics import YOLO
import config

def main():
    print("=== PROGRAM KALIBRASI PIXEL PENDETEKSIAN YOLO ===")
    print(f"Membuka Kamera Atas (Index: {config.CAM_ATAS_INDEX})...")
    print(f"Memuat Model: {config.MODEL_PATH.name}...")
    
    # 1. Load Model (Support TensorRT / PyTorch)
    if config.MODEL_PATH.suffix == '.engine':
        model = YOLO(str(config.MODEL_PATH), task='detect')
        print("[INFO] Menggunakan model TensorRT.")
    else:
        model = YOLO(str(config.MODEL_PATH))
        print("[INFO] Menggunakan model standar.")

    # 2. Buka Kamera
    cap = cv2.VideoCapture(config.CAM_ATAS_INDEX)
    
    # SANGAT PENTING: Samakan resolusi dengan vision_worker.py (320x240)
    # Ini memastikan nilai perhitungan pixel persis 100% sama dengan program asli
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
    
    if not cap.isOpened():
        print("[ERROR] Gagal membuka kamera. Cek koneksi kamera atas Anda!")
        return
        
    print("\n[INFO] Kamera berhasil dibuka.")
    print("[INFO] Arahkan kapal ke box untuk melihat nilai pixelnya.")
    print("[INFO] Tekan tombol 'q' pada keyboard di layar kamera untuk keluar.\n")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue
            
        # 3. Jalankan Deteksi
        results = model(frame, verbose=False, conf=0.5)
        
        # Gambar kotak bawaan YOLO
        annotated_frame = results[0].plot()
        
        # 4. Hitung & Tampilkan Nilai Total Pixel tiap box
        for result in results:
            for box in result.boxes:
                name = model.names[int(box.cls[0])].upper()
                
                # Menghitung luasan bounding box (width * height)
                w = box.xywh[0][2].item()
                h = box.xywh[0][3].item()
                area = w * h
                
                # Koordinat untuk meletakkan teks UI
                x_min = int(box.xyxy[0][0].item())
                y_min = int(box.xyxy[0][1].item())
                
                # Siapkan Teks Area
                text = f"TOTAL PIXEL: {area:.0f}"
                
                # Beri background hitam agar teks kuning menonjol
                (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 2)
                cv2.rectangle(annotated_frame, (x_min, y_min - 25), (x_min + tw + 5, y_min), (0, 0, 0), -1)
                
                # Cetak teks ke layar video
                cv2.putText(annotated_frame, text, (x_min + 2, y_min - 6), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 2)
                            
                # Cetak juga ke terminal (agar bisa Anda catat)
                print(f"[KALIBRASI] Objek: {name} | Luas Kotak: {area:.0f} px")

        # 5. Tampilkan Jendela Video Live
        cv2.imshow("Kalibrasi Threshold Jarak (YOLO)", annotated_frame)
        
        # Keluar jika tombol 'q' ditekan
        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("\n[INFO] Menutup program kalibrasi...")
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
