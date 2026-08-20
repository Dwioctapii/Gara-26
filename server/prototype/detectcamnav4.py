import cv2
import time
import serial
import threading
import os
import json
from ultralytics import YOLO

# === TAMBAHAN UNTUK HTTP SERVER FOTO ===
import http.server
import socketserver

# === GLOBAL VARIABLE UNTUK THREAD SERIAL ===
latest_vx = 0.0
latest_w = 0.0          
current_heading = 0.0   
status_misi = 0         
is_running = True
force_mode = False 
lock = threading.Lock()

# === GLOBAL VARIABLE UNTUK FOTO ===
foto_boxgreen_terkirim = False
foto_boxblue_terkirim = False
frame_bawah_terbaru = None      
kamera_bawah_aktif = False

# === 0. INISIALISASI FILE (Hapus Foto Lama) ===
if os.path.exists("atas.jpg"):
    os.remove("atas.jpg")
if os.path.exists("bawah.jpg"):
    os.remove("bawah.jpg")
print("[INFO] File foto inspeksi lama telah dibersihkan.")

# === 1. KONEKSI SERIAL TEENSY ===
SERIAL_PORT = '/dev/ttyACM2'  
BAUD_RATE = 115200

try:
    teensy = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
    time.sleep(1)
    print(f"\n[SUKSES] TEENSY TERHUBUNG DI {SERIAL_PORT}!\n")
except Exception as e:
    print(f"\n[CRITICAL ERROR] Gagal konek ke {SERIAL_PORT}. Thruster tidak akan jalan.")
    print(f"Pesan Error: {e}\n")
    teensy = None

# === 2. THREAD SERIAL (20 Hz) ===
def serial_worker():
    global latest_vx, latest_w, current_heading, status_misi, is_running, force_mode
    while is_running:
        if teensy is not None and teensy.is_open:
            try:
                while teensy.in_waiting > 0:
                    baris = teensy.readline().decode('utf-8', errors='ignore').strip()
                    if baris.startswith("SENSOR"):
                        parts = baris.split(',')
                        if len(parts) >= 2:
                            with lock:
                                current_heading = float(parts[1])

                with lock:
                    v_send = latest_vx
                    w_send = latest_w
                    h_aktual = current_heading
                    stat_send = status_misi
                    is_forced = force_mode

                if is_forced:
                    target_heading = h_aktual
                    stat_send = 1
                    v_send = 20 
                elif stat_send == 1:
                    target_heading = h_aktual + w_send
                    if target_heading >= 360.0: target_heading -= 360.0
                    if target_heading < 0.0: target_heading += 360.0
                else:
                    target_heading = 0.0
                    v_send = 0.0

                data_kirim = f"<{stat_send},{target_heading:.1f},{int(v_send)}>"
                teensy.write(data_kirim.encode('utf-8'))
                
            except Exception as e:
                pass
        
        time.sleep(0.05) 

serial_thread = threading.Thread(target=serial_worker, daemon=True)
serial_thread.start()

# === 3. THREAD KAMERA BAWAH (Anti-Lag Buffer) ===
def worker_kamera_bawah():
    global frame_bawah_terbaru, is_running, kamera_bawah_aktif
    try:
        cap_bawah = cv2.VideoCapture(2)
        cap_bawah.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap_bawah.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        if cap_bawah.isOpened():
            print("[INFO] Kamera Bawah Berhasil Dibuka.")
            kamera_bawah_aktif = True
            while is_running:
                ret, frame = cap_bawah.read()
                if ret:
                    with lock:
                        frame_bawah_terbaru = frame
                time.sleep(0.03) 
        else:
            print("[ERROR] Kamera Bawah (Port 2) tidak ditemukan.")
    except Exception as e:
        print(f"[ERROR] Kamera Bawah bermasalah: {e}")
    finally:
        if 'cap_bawah' in locals() and cap_bawah.isOpened():
            cap_bawah.release()

thread_kam_bawah = threading.Thread(target=worker_kamera_bawah, daemon=True)
thread_kam_bawah.start()

# === 4. THREAD HTTP SERVER (Menggantikan WebSocket) ===
class HandlerFoto(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # 1. Endpoint untuk cek ketersediaan file
        if self.path == '/status':
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*") # Cegah CORS Error di HTML
            self.end_headers()
            status_foto = {
                "atas": os.path.exists("atas.jpg"),
                "bawah": os.path.exists("bawah.jpg")
            }
            self.wfile.write(json.dumps(status_foto).encode())
            return
        
        # 2. Endpoint untuk mengambil file gambar langsung
        if self.path == '/atas.jpg' or self.path == '/bawah.jpg':
            if os.path.exists(self.path[1:]): # [1:] hilangkan slash '/'
                self.send_response(200)
                self.send_header("Content-type", "image/jpeg")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store") # Paksa browser tidak cache
                self.end_headers()
                with open(self.path[1:], 'rb') as f:
                    self.wfile.write(f.read())
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        # Abaikan path lain agar aman
        self.send_response(404)
        self.end_headers()

def jalankan_server_http_foto():
    PORT = 8766
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), HandlerFoto) as httpd:
        print(f"\n[INFO] Server HTTP Gambar aktif di Port {PORT}")
        print(f"URL Cek Status : http://<ip_kapal>:{PORT}/status")
        print(f"URL Foto Atas  : http://<ip_kapal>:{PORT}/atas.jpg")
        httpd.serve_forever()

thread_http_gambar = threading.Thread(target=jalankan_server_http_foto, daemon=True)
thread_http_gambar.start()


# === 5. PROGRAM UTAMA OPENCV & YOLO ===
if __name__ == '__main__':
    model = YOLO('/home/lahbako-san/Downloads/sagara/detecbuoy/YoloV8asv/YoloV8/runs/detect/train-4/weights/best.pt')

    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    CAMERA_FOV = 60.0  
    BASE_SPEED = 15.0  

    while cap.isOpened():
        success, frame = cap.read()
        if not success:
            break

        height, width, _ = frame.shape
        center_x = width // 2
        posisi_asal_kapal = (center_x, height)

        results = model.predict(source=frame, conf=0.4, device='cpu', imgsz=416, verbose=False)

        list_hijau = []
        list_merah = []

        # LOGIKA DETEKSI BOX & BUOY
        for r in results:
            boxes = r.boxes
            for box in boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cx = int((x1 + x2) / 2)
                cy = int((y1 + y2) / 2)
                area = (x2 - x1) * (y2 - y1)
                cls_id = int(box.cls[0])
                nama_kelas = model.names[cls_id]

                # === BUOY ===
                if nama_kelas == 'buoygreen':
                    list_hijau.append({'posisi': (cx, cy), 'area': area})
                elif nama_kelas == 'buoyred':
                    list_merah.append({'posisi': (cx, cy), 'area': area})
                
                # === BOX GREEN (Difoto pakai kamera ATAS) ===
                elif nama_kelas == 'boxgreen':
                    if not foto_boxgreen_terkirim:
                        print("\n[!!] BOX GREEN TERDETEKSI! Menyimpan atas.jpg...")
                        with lock:
                            frame_kirim = frame.copy()
                            cv2.rectangle(frame_kirim, (x1, y1), (x2, y2), (0, 255, 0), 3)
                            cv2.putText(frame_kirim, "BOX GREEN", (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                            
                            # Simpan Langsung ke Sistem File
                            cv2.imwrite("atas.jpg", frame_kirim)
                            
                            foto_boxgreen_terkirim = True 

                # === BOX BLUE (Difoto pakai kamera BAWAH) ===
                elif nama_kelas == 'boxblue':
                    if not foto_boxblue_terkirim:
                        print("\n[!!] BOX BLUE TERDETEKSI! Menyimpan bawah.jpg...")
                        with lock:
                            if frame_bawah_terbaru is not None:
                                frame_kirim_bawah = frame_bawah_terbaru.copy()
                                
                                # Simpan Langsung ke Sistem File
                                cv2.imwrite("bawah.jpg", frame_kirim_bawah)
                                print(">> Gambar bawah.jpg diamankan.")
                            else:
                                print(">> [GAGAL] Kamera bawah belum siap.")
                                
                            foto_boxblue_terkirim = True 


        # LOGIKA NAVIGASI PENGHINDARAN BUOY
        status_target = "NO TARGET"

        if len(list_hijau) > 0 and len(list_merah) > 0:
            daftar_pasangan_gerbang = []
            for h in list_hijau:
                for m in list_merah:
                    avg_area = (h['area'] + m['area']) / 2.0
                    daftar_pasangan_gerbang.append({'hijau': h['posisi'], 'merah': m['posisi'], 'avg_area': avg_area})

            if len(daftar_pasangan_gerbang) > 0:
                daftar_pasangan_gerbang.sort(key=lambda item: item['avg_area'], reverse=True)
                pasangan = daftar_pasangan_gerbang[0]
                
                cv2.circle(frame, pasangan['hijau'], 6, (0, 255, 0), -1)
                cv2.circle(frame, pasangan['merah'], 6, (0, 0, 255), -1)
                cv2.line(frame, pasangan['hijau'], pasangan['merah'], (255, 0, 0), 2)

                mid_x = int((pasangan['hijau'][0] + pasangan['merah'][0]) / 2)
                mid_y = int((pasangan['hijau'][1] + pasangan['merah'][1]) / 2)
                titik_target = (mid_x, mid_y)
                
                cv2.line(frame, posisi_asal_kapal, titik_target, (0, 255, 255), 2)
                
                error_x = mid_x - center_x
                heading_angle = (error_x / center_x) * (CAMERA_FOV / 2.0)

                status_target = "TARGET LOCKED"
                with lock:
                    latest_vx = BASE_SPEED
                    latest_w = heading_angle
                    status_misi = 1 
        else:
            with lock:
                latest_vx = 0.0
                latest_w = 0.0
                status_misi = 0 

        with lock:
            tampil_kompas = current_heading
            stat_aktif = "FORCE RUN (TEST)" if force_mode else status_target

        cv2.putText(frame, f"STATUS : {stat_aktif}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.putText(frame, f"KOMPAS : {tampil_kompas:.1f} Deg", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        
        if foto_boxgreen_terkirim:
            cv2.putText(frame, "GREEN BOX CAPTURED", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        if foto_boxblue_terkirim:
            cv2.putText(frame, "BLUE BOX CAPTURED", (20, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)

        cv2.imshow("Navigasi ASV", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('f') or key == ord('F'):
            with lock:
                force_mode = not force_mode 
        elif key == ord('r') or key == ord('R'):
            with lock:
                foto_boxgreen_terkirim = False
                foto_boxblue_terkirim = False
                # Hapus file saat direset secara manual
                if os.path.exists("atas.jpg"): os.remove("atas.jpg")
                if os.path.exists("bawah.jpg"): os.remove("bawah.jpg")
                print(">> [RESET] Kamera siap memotret ulang dan file dihapus!")

    is_running = False
    if teensy is not None and teensy.is_open:
        teensy.write("<0,0.0,0>".encode('utf-8'))
        teensy.close()
    cap.release()
    cv2.destroyAllWindows()