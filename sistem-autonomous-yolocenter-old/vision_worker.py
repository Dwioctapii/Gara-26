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

import config


# ═════════════════════════════════════════════════════════════════════════════
# Threaded Camera Grabber
# ═════════════════════════════════════════════════════════════════════════════

class ThreadedCamera:
    """
    Pembaca kamera berbasis thread — menghilangkan blocking I/O dari loop inferensi.

    Masalah tanpa kelas ini:
        cv2.VideoCapture.read() menunggu frame fisik dari hardware USB (~33ms per kamera).
        Dengan 2 kamera serial: 33ms + 33ms = 66ms terbuang hanya untuk baca kamera,
        padahal CPU diam saja menunggu hardware.

    Solusi:
        Thread background terus memanggil cap.read() dan menyimpan frame terbaru ke
        self._frame menggunakan threading.Lock.
        Thread inferensi YOLO tinggal memanggil .read() yang langsung return
        frame dari memori (< 1ms) — tidak perlu menunggu hardware sama sekali.

    Timing per frame setelah optimasi ini:
        Sebelum : 33ms (kamera 1) + 33ms (kamera 2) + YOLO = ~116ms → ~8 FPS
        Sesudah :  1ms (buffer)   +  1ms (buffer)   + YOLO = ~52ms  → ~20 FPS (x2.5)
    """

    def __init__(self, index: int, width: int = 320, height: int = 240) -> None:
        self._cap = cv2.VideoCapture(index)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        # Paksa buffer kamera sekecil mungkin agar frame selalu fresh (tidak stale)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._frame: "np.ndarray | None" = None
        self._ok:    bool                = False
        self._lock   = threading.Lock()
        self._stop   = threading.Event()

    def start(self) -> "ThreadedCamera":
        """Mulai thread background dan tunggu sampai frame pertama siap (maks 3 detik)."""
        threading.Thread(target=self._run, daemon=True, name=f"cam-{id(self)}").start()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            with self._lock:
                if self._frame is not None:
                    return self
            time.sleep(0.05)
        return self

    def _run(self) -> None:
        """Loop background: terus grab frame kamera tanpa henti."""
        while not self._stop.is_set():
            ok, frame = self._cap.read()
            with self._lock:
                self._ok    = ok
                self._frame = frame
            # Yield agar GIL berpindah ke thread lain, tidak sleep lama
            time.sleep(0.001)

    def read(self) -> "tuple[bool, np.ndarray | None]":
        """Ambil frame terbaru dari buffer (< 1ms, tidak blocking hardware)."""
        with self._lock:
            return self._ok, (self._frame.copy() if self._frame is not None else None)

    def release(self) -> None:
        """Hentikan thread dan lepas resource kamera."""
        self._stop.set()
        self._cap.release()

    @property
    def is_opened(self) -> bool:
        return self._cap.isOpened()


# ═════════════════════════════════════════════════════════════════════════════
# PID Controller
# ═════════════════════════════════════════════════════════════════════════════

class BuoyPIDController:
    """
    PID controller untuk kendali servo kemudi berdasarkan error posisi buoy.

    Output PID:
        u(t) = Kp·e(t)  +  Ki·∫e(t)dt  +  Kd·(de/dt)

    Lalu dikonversi ke PWM servo:
        PWM = neutral - u(t)          ← tanda minus: koreksi berlawanan arah error
        PWM di-clamp ke [min, max]

    Parameter
    ---------
    kp             : gain proporsional  (langsung koreksi error sekarang)
    ki             : gain integral      (hilangkan steady-state error)
    kd             : gain derivatif     (peredam osilasi)
    integral_limit : batas anti-windup  (cegah integral meledak)
    deadband       : zona mati (px)     (cegah servo bergetar saat hampir lurus)
    servo_neutral  : PWM saat lurus (us)
    servo_min      : PWM minimum   (us)
    servo_max      : PWM maksimum  (us)
    """

    def __init__(
        self,
        kp:             float,
        ki:             float,
        kd:             float,
        integral_limit: float,
        deadband:       float,
        servo_neutral:  int,
        servo_min:      int,
        servo_max:      int,
    ) -> None:
        self.kp             = kp
        self.ki             = ki
        self.kd             = kd
        self.integral_limit = integral_limit
        self.deadband       = deadband
        self.servo_neutral  = servo_neutral
        self.servo_min      = servo_min
        self.servo_max      = servo_max

        # State internal PID
        self._integral:   float = 0.0
        self._prev_error: float = 0.0
        self._prev_time:  float = 0.0

    def reset(self) -> None:
        """Reset state PID — panggil saat buoy hilang atau gain berubah."""
        self._integral   = 0.0
        self._prev_error = 0.0
        self._prev_time  = 0.0

    def compute(self, error: float) -> tuple:
        """
        Hitung output PID dan konversi ke PWM servo.

        Returns
        -------
        servo_pwm : int   — nilai PWM servo dalam µs
        pid_terms : dict  — rincian tiap komponen PID (untuk debug/monitoring)
        """
        now = time.monotonic()
        dt  = (now - self._prev_time) if self._prev_time != 0.0 else 0.033
        dt  = max(dt, 0.001)
        self._prev_time = now

        # Dead-band: jika error sangat kecil → anggap lurus, jangan koreksi
        if abs(error) <= self.deadband:
            self._integral   = 0.0
            self._prev_error = error
            return self.servo_neutral, {
                "p": 0.0, "i": 0.0, "d": 0.0, "u": 0.0, "dt": dt
            }

        # Komponen Proporsional
        p_term = self.kp * error

        # Komponen Integral dengan anti-windup
        self._integral += error * dt
        self._integral  = max(-self.integral_limit,
                              min(self.integral_limit, self._integral))
        i_term = self.ki * self._integral

        # Komponen Derivatif
        d_term = self.kd * (error - self._prev_error) / dt
        self._prev_error = error

        # Output total
        u   = p_term + i_term + d_term
        pwm = self.servo_neutral - u
        pwm = int(max(self.servo_min, min(self.servo_max, pwm)))

        pid_terms = {
            "p":  round(p_term, 2),
            "i":  round(i_term, 2),
            "d":  round(d_term, 2),
            "u":  round(u,      2),
            "dt": round(dt,     4),
        }
        return pwm, pid_terms


# ═════════════════════════════════════════════════════════════════════════════
# Vision Worker
# ═════════════════════════════════════════════════════════════════════════════

class VisionWorker:
    def __init__(self, cam_atas: int, cam_bawah: int, model_path, photo_dir, store) -> None:
        self.cam_atas, self.cam_bawah = cam_atas, cam_bawah
        self.model_path, self.photo_dir, self.store = model_path, photo_dir, store

        # ── Parameter garis panduan oranye ───────────────────────────────────
        self.guide_p1: tuple = config.GUIDE_LINE_P1
        self.guide_p2: tuple = config.GUIDE_LINE_P2

        # ── Parameter servo ───────────────────────────────────────────────────
        self.servo_neutral:    int = config.SERVO_NEUTRAL
        self.red_min_area:     int = config.RED_BUOY_MIN_AREA
        self.green_min_area:   int = config.GREEN_BUOY_MIN_AREA
        self.search_offset:    int = config.SERVO_SEARCH_OFFSET

        # ── PID Controller ────────────────────────────────────────────────────
        self.pid = BuoyPIDController(
            kp             = config.SERVO_KP,
            ki             = config.SERVO_KI,
            kd             = config.SERVO_KD,
            integral_limit = config.SERVO_INTEGRAL_LIMIT,
            deadband       = config.SERVO_DEADBAND,
            servo_neutral  = config.SERVO_NEUTRAL,
            servo_min      = config.SERVO_MIN,
            servo_max      = config.SERVO_MAX,
        )

        # ── Prakalkulasi gradien garis panduan ───────────────────────────────
        x1, y1 = self.guide_p1
        x2, y2 = self.guide_p2
        if y2 != y1:
            self._m = (x2 - x1) / (y2 - y1)
            self._c = x1 - self._m * y1
        else:
            self._m = 0.0
            self._c = (x1 + x2) / 2.0

        # ── Hot-reload PID tracking ───────────────────────────────────────────
        # Menyimpan versi terakhir yang sudah diterapkan.
        # Cek ini hanya membandingkan 2 integer per frame → sangat ringan.
        self._last_pid_version: int = 0

        # Tulis nilai awal PID ke store agar GUI bisa baca sebagai nilai default
        self.store.update({
            "pid_config": {
                "kp":             self.pid.kp,
                "ki":             self.pid.ki,
                "kd":             self.pid.kd,
                "integral_limit": self.pid.integral_limit,
                "deadband":       self.pid.deadband,
                "_version":       0,
            }
        })

        # ── FPS Tracking ──────────────────────────────────────────────────────
        self._fps_history = []
        self._last_frame_time = time.monotonic()

    # ─────────────────────────────────────────────────────────────────────────
    # Thread utama
    # ─────────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="vision").start()

    def _run(self) -> None:
        # ── Muat model YOLO ───────────────────────────────────────────────────
        model      = None
        model_type = "NONE"
        if YOLO:
            engine_path = self.model_path.with_suffix('.engine')
            pt_path     = self.model_path.with_suffix('.pt')
            if engine_path.exists():
                model      = YOLO(str(engine_path), task='detect')
                model_type = "TensorRT (.engine) — GPU"
                print(f"[VISION] ✓ Model {model_type} berhasil dimuat: {engine_path.name}")
                print(f"[VISION]   → Inferensi berjalan di GPU (device=0), imgsz=640")
            elif pt_path.exists():
                model      = YOLO(str(pt_path))
                model_type = "PyTorch (.pt) — CPU/GPU"
                print(f"[VISION] ✓ Model {model_type} berhasil dimuat: {pt_path.name}")
                print(f"[VISION]   → FPS akan lebih lambat dibanding TensorRT.")
                print(f"[VISION]   → Compile ke .engine dengan: yolo export model=best.pt format=engine")

        if not model:
            print("[VISION] ✗ YOLO/model tidak tersedia; kamera tetap berjalan tanpa deteksi.")
        else:
            print(f"[VISION] Pipeline siap: ThreadedCamera × 2 | YOLO {model_type} | imgsz=640")

        # ── Inisialisasi ThreadedCamera (non-blocking, masing-masing thread sendiri) ──
        # ThreadedCamera.start() menunggu frame pertama siap (maks 3 detik)
        # sehingga loop inferensi di bawah tidak langsung menerima None.
        print("[VISION] Menginisialisasi kamera atas (ThreadedCamera)...")
        top    = ThreadedCamera(self.cam_atas,  320, 240).start()
        print("[VISION] Menginisialisasi kamera bawah (ThreadedCamera)...")
        bottom = ThreadedCamera(self.cam_bawah, 320, 240).start()
        print("[VISION] Kedua kamera siap — memulai loop inferensi tanpa blocking.")

        try:
            while True:
                # Ambil frame dari buffer (< 1ms, tidak menunggu hardware)
                ok_atas,  frame_atas  = top.read()
                ok_bawah, frame_bawah = bottom.read()

                if not ok_atas or not ok_bawah:
                    err_img = np.zeros((240, 320, 3), dtype=np.uint8)
                    cv2.putText(err_img, "ERROR: KAMERA TERPUTUS!", (20, 120),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    self.store.set_live_frame(err_img)
                    time.sleep(1.0)
                    continue

                if model:
                    self._detect(model, frame_atas, frame_bawah)
                else:
                    err_img = np.zeros((240, 320, 3), dtype=np.uint8)
                    cv2.putText(err_img, "ERROR: MODEL TIDAK TERSEDIA", (15, 120),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
                    self.store.set_live_frame(err_img)

                # Throttle minimal: cegah 100% CPU usage, tapi tidak membatasi FPS
                # seperti sleep(0.03) yang lama. Inferensi YOLO sudah jadi rate-limiter
                # alami (15–50ms per frame tergantung model).
                time.sleep(0.001)
        finally:
            # Pastikan resource kamera dilepas saat thread berhenti
            top.release()
            bottom.release()
            print("[VISION] Kamera dilepas (ThreadedCamera released).")

    # ─────────────────────────────────────────────────────────────────────────
    # Hot-reload PID (dipanggil tiap frame, sangat ringan)
    # ─────────────────────────────────────────────────────────────────────────

    def _sync_pid_config(self) -> None:
        """
        Cek apakah GUI menyimpan nilai PID baru (via store['pid_config']['_version']).

        Operasi ini sangat ringan: hanya membaca 1 integer dan membandingkannya.
        Tidak ada lock berat atau network call — hanya dict lookup Python biasa.
        Pembaruan aktual (bagian dalam if) hanya terjadi saat user klik SAVE di GUI.
        """
        cfg     = self.store.pid_snapshot()
        version = cfg.get("_version", 0)

        if version == self._last_pid_version:
            return   # Tidak ada perubahan → langsung kembali (< 1 µs)

        # ── Perubahan terdeteksi: terapkan gain baru ──────────────────────────
        self._last_pid_version = version
        self.pid.kp             = float(cfg.get("kp",             self.pid.kp))
        self.pid.ki             = float(cfg.get("ki",             self.pid.ki))
        self.pid.kd             = float(cfg.get("kd",             self.pid.kd))
        self.pid.integral_limit = float(cfg.get("integral_limit", self.pid.integral_limit))
        self.pid.deadband       = float(cfg.get("deadband",       self.pid.deadband))

        # Reset state internal agar tidak ada carry-over dari nilai lama
        self.pid.reset()

        print(
            f"[VISION] PID hot-reload v{version}: "
            f"Kp={self.pid.kp}  Ki={self.pid.ki}  Kd={self.pid.kd}  "
            f"DB={self.pid.deadband}  ILim={self.pid.integral_limit}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Deteksi utama
    # ─────────────────────────────────────────────────────────────────────────

    def _detect(self, model, frame_atas, frame_bawah) -> None:
        # Cek hot-reload PID dari GUI (sangat ringan, < 1 µs jika tidak ada perubahan)
        self._sync_pid_config()

        snapshot = self.store.snapshot()["detection"]
        # Optimasi: paksa gunakan GPU (device=0) dan ukuran sesuai file .engine (640)
        # Tambahan agnostic_nms=True: Mencegah buoy dan box terdeteksi bertumpuk di 1 objek fisik
        results  = model(frame_atas, verbose=False, conf=0.5, device=0, imgsz=640, agnostic_nms=True)
        
        # Optimasi CPU: Jangan gunakan results[0].plot() bawaan YOLO yang berat. 
        # Kita gambar (copy) frame asli, lalu gambar kotak manual.
        annotated_frame = frame_atas.copy()

        red_candidates   = []
        green_candidates = []
        # Tracking area terbesar boxgreen/boxblue per frame (untuk status GUI)
        best_area_green = 0
        best_area_blue  = 0

        for result in results:
            for box in result.boxes:
                name      = model.names[int(box.cls[0])].lower()
                cx        = box.xywh[0][0].item()
                cy        = box.xywh[0][1].item()
                w         = box.xywh[0][2].item()
                h         = box.xywh[0][3].item()
                bbox_area = w * h

                # ── Filter Aspek Rasio untuk membedakan Box dan Buoy ─────────
                # Jika objek terdeteksi sebagai "box" tapi bentuk bounding box-nya
                # sangat jangkung/berdiri (tinggi jauh lebih besar dari lebar),
                # kemungkinan besar itu adalah buoy yang salah klasifikasi.
                if ("blue" in name or "green" in name) and not "buoy" in name:
                    if h > w * 1.2:
                        continue  # Abaikan salah deteksi ini (anggap bukan box)

                # --- Gambar Bounding Box Ringan (Manual) ---
                x1 = int(cx - w/2)
                y1 = int(cy - h/2)
                x2 = int(cx + w/2)
                y2 = int(cy + h/2)
                
                color = (0, 0, 255) if "red" in name else (0, 255, 0) if "green" in name else (255, 0, 0)
                cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(annotated_frame, name, (x1, max(15, y1 - 5)), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
                # -------------------------------------------

                # ── Misi foto: boxblue & boxgreen ────────────────────────────
                if "blue" in name and not "buoy" in name:
                    best_area_blue = max(best_area_blue, int(bbox_area))
                    if not snapshot["foto_bawah_ready"] and bbox_area >= 5000:
                        img_to_save = frame_bawah if frame_bawah is not None else frame_atas
                        cv2.imwrite(str(self.photo_dir / "bawah.jpg"), img_to_save)
                        self.store.update({
                            "detection": {
                                "label": "BOXBLUE (LOCKED & SAVED)",
                                "foto_bawah_ready": True,
                                "area_blue": int(bbox_area),
                            }
                        })
                        self.store.set_live_frame(annotated_frame)
                        return

                if "green" in name and not "buoy" in name:
                    best_area_green = max(best_area_green, int(bbox_area))
                    if not snapshot["foto_atas_ready"] and bbox_area >= 5000:
                        cv2.imwrite(str(self.photo_dir / "atas.jpg"), frame_atas)
                        self.store.update({
                            "detection": {
                                "label": "BOXGREEN (LOCKED & SAVED)",
                                "foto_atas_ready": True,
                                "area_green": int(bbox_area),
                            }
                        })
                        self.store.set_live_frame(annotated_frame)
                        return

                # ── Kumpulkan kandidat buoy merah ────────────────────────────
                if "buoyred" in name and bbox_area >= self.red_min_area:
                    red_candidates.append((bbox_area, cx, cy))

                # ── Kumpulkan kandidat buoy hijau ────────────────────────────
                if "buoygreen" in name and bbox_area >= self.green_min_area:
                    green_candidates.append((bbox_area, cx, cy))

        # ── Kirim area live ke store (hanya jika ada deteksi, agar angka terlihat) ──
        det_patch = {}
        if best_area_green > 0:
            det_patch["area_green"] = best_area_green
            det_patch["label"]      = f"BOXGREEN terdeteksi ({best_area_green:,} px²)"
        if best_area_blue > 0:
            det_patch["area_blue"]  = best_area_blue
            det_patch["label"]      = f"BOXBLUE terdeteksi ({best_area_blue:,} px²)"
        if det_patch and not snapshot["foto_atas_ready"] and not snapshot["foto_bawah_ready"]:
            self.store.update({"detection": det_patch})

        # ── Pilih buoy terdekat (bbox area terbesar) dari masing-masing warna ──
        best_red   = max(red_candidates,   key=lambda r: r[0]) if red_candidates   else None
        best_green = max(green_candidates, key=lambda r: r[0]) if green_candidates else None

        # ── Buoy-following: 4 kondisi ─────────────────────────────────────────
        if best_red and best_green:
            # ── KONDISI 1: Kedua buoy terdeteksi → koreksi ke titik tengah ───
            cx_mid = (best_red[1] + best_green[1]) / 2.0
            cy_mid = (best_red[2] + best_green[2]) / 2.0
            error, x_target      = self._compute_guide_error(cx_mid, cy_mid)
            servo_pwm, pid_terms = self.pid.compute(error)

            self.store.update({
                "buoy": {
                    "detected":   True,
                    "mode":       "BOTH",
                    "cx":         round(cx_mid,          1),
                    "cy":         round(cy_mid,          1),
                    "cx_red":     round(best_red[1],     1),
                    "cx_green":   round(best_green[1],   1),
                    "x_target":   round(x_target,        1),
                    "error_px":   round(error,           1),
                    "servo_pwm":  servo_pwm,
                    "pid":        pid_terms,
                }
            })
            self._draw_gate_overlay(annotated_frame, best_red, best_green,
                                    cx_mid, cy_mid, x_target, error, servo_pwm, pid_terms)

        elif best_red and not best_green:
            # ── KONDISI 2: Hanya buoyred → belok KANAN cari buoygreen ────────
            self.pid.reset()
            servo_pwm = min(self.servo_neutral + self.search_offset, self.pid.servo_max)
            self.store.update({
                "buoy": {
                    "detected":  True,
                    "mode":      "RED_ONLY",
                    "cx":        round(best_red[1], 1),
                    "cy":        round(best_red[2], 1),
                    "x_target":  0,
                    "error_px":  0.0,
                    "servo_pwm": servo_pwm,
                    "pid":       {"p": 0.0, "i": 0.0, "d": 0.0, "u": 0.0, "dt": 0.0},
                }
            })
            self._draw_search_overlay(annotated_frame, best_red[1], best_red[2],
                                      "ONLY RED -> SEARCH RIGHT", servo_pwm)

        elif best_green and not best_red:
            # ── KONDISI 3: Hanya buoygreen → belok KIRI cari buoyred ─────────
            self.pid.reset()
            servo_pwm = max(self.servo_neutral - self.search_offset, self.pid.servo_min)
            self.store.update({
                "buoy": {
                    "detected":  True,
                    "mode":      "GREEN_ONLY",
                    "cx":        round(best_green[1], 1),
                    "cy":        round(best_green[2], 1),
                    "x_target":  0,
                    "error_px":  0.0,
                    "servo_pwm": servo_pwm,
                    "pid":       {"p": 0.0, "i": 0.0, "d": 0.0, "u": 0.0, "dt": 0.0},
                }
            })
            self._draw_search_overlay(annotated_frame, best_green[1], best_green[2],
                                      "ONLY GREEN -> SEARCH LEFT", servo_pwm)

        else:
            # ── KONDISI 4: Tidak ada buoy → servo diam di neutral ─────────────
            self.pid.reset()
            self.store.update({
                "buoy": {
                    "detected":  False,
                    "mode":      "NONE",
                    "cx":        0, "cy": 0, "x_target": 0,
                    "error_px":  0.0,
                    "servo_pwm": self.servo_neutral,
                    "pid":       {"p": 0.0, "i": 0.0, "d": 0.0, "u": 0.0, "dt": 0.0},
                }
            })
            self._draw_guide_line(annotated_frame)
        # ── Hitung dan Tampilkan FPS ──────────────────────────────────────────
        now = time.monotonic()
        dt = now - self._last_frame_time
        self._last_frame_time = now
        fps = 1.0 / dt if dt > 0 else 0.0

        self._fps_history.append(fps)
        if len(self._fps_history) > 15:
            self._fps_history.pop(0)
        avg_fps = sum(self._fps_history) / len(self._fps_history)

        cv2.putText(annotated_frame, f"FPS: {avg_fps:.1f}", (240, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        self.store.set_live_frame(annotated_frame)

    # ─────────────────────────────────────────────────────────────────────────
    # Kalkulasi garis panduan
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_guide_error(self, x_buoy: float, y_buoy: float):
        """
        Hitung error posisi (midpoint buoy atau buoy tunggal) terhadap garis panduan oranye.

        Formula: X_target(Y) = m * Y + c
            m = (X2 - X1) / (Y2 - Y1)
            c = X1 - m * Y1

        Returns: (error, x_target)
            error positif = target di KANAN garis → belok kiri
            error negatif = target di KIRI  garis → belok kanan
        """
        x_target = self._m * y_buoy + self._c
        return x_buoy - x_target, x_target

    # ─────────────────────────────────────────────────────────────────────────
    # Overlay visual di frame kamera
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_guide_line(self, frame: np.ndarray) -> None:
        """Gambar garis panduan oranye saja (tanpa info buoy)."""
        cv2.line(frame, self.guide_p1, self.guide_p2, (0, 165, 255), 2)

    def _draw_gate_overlay(
        self,
        frame:     np.ndarray,
        best_red:  tuple,
        best_green: tuple,
        cx_mid:    float,
        cy_mid:    float,
        x_target:  float,
        error:     float,
        servo_pwm: int,
        pid_terms: dict,
    ) -> None:
        """
        Overlay kondisi BOTH (kedua buoy terdeteksi):
          - Kapal akan dikoreksi agar titik tengah (midpoint) di antara kedua buoy
            berada tepat di atas garis panduan (garis tengah frame).
          - Titik buoy merah  (merah)
          - Titik buoy hijau  (hijau)
          - Garis gate antara keduanya (putih)
          - Titik MIDPOINT    (kuning) di tengah gate
          - Titik TARGET      (oranye) di garis panduan
          - Garis ERROR       (cyan) antara midpoint dan target
          - Garis panduan     (oranye tipis)
          - Teks info
        """
        orange = (0, 165, 255)
        yellow = (0, 255, 255)
        green  = (0, 255, 0)
        red    = (0, 0, 255)
        cyan   = (255, 255, 0)
        white  = (255, 255, 255)

        ix_red   = int(best_red[1]);   iy_red   = int(best_red[2])
        ix_grn   = int(best_green[1]); iy_grn   = int(best_green[2])
        ix_mid   = int(cx_mid);        iy_mid   = int(cy_mid)
        ix_tgt   = int(x_target)

        # Garis panduan oranye (referensi)
        cv2.line(frame, self.guide_p1, self.guide_p2, orange, 1)

        # Garis gate merah–hijau
        cv2.line(frame, (ix_red, iy_red), (ix_grn, iy_grn), white, 2)

        # Titik buoy merah
        cv2.circle(frame, (ix_red, iy_red), 8, red,   -1)
        cv2.circle(frame, (ix_red, iy_red), 8, white,  1)

        # Titik buoy hijau
        cv2.circle(frame, (ix_grn, iy_grn), 8, green, -1)
        cv2.circle(frame, (ix_grn, iy_grn), 8, white,  1)

        # Titik midpoint (kuning)
        cv2.circle(frame, (ix_mid, iy_mid), 7, yellow, -1)
        cv2.circle(frame, (ix_mid, iy_mid), 7, white,   1)

        # Titik target di garis panduan (oranye terang)
        cv2.circle(frame, (ix_tgt, iy_mid), 5, orange, -1)

        # Garis error cyan
        cv2.line(frame, (ix_tgt, iy_mid), (ix_mid, iy_mid), cyan, 2)

        # ── Teks Info dihilangkan sesuai permintaan (hanya menyisakan visual garis) ──
        # Teks FPS tetap akan muncul karena digambar terpisah di akhir _detect

    def _draw_search_overlay(
        self,
        frame:     np.ndarray,
        cx:        float,
        cy:        float,
        label:     str,
        servo_pwm: int,
    ) -> None:
        """
        Overlay kondisi SEARCH (hanya satu buoy terdeteksi):
          - Titik buoy yang terdeteksi
          - Teks mode + arah pencarian + nilai servo
        """
        orange = (0, 165, 255)
        white  = (255, 255, 255)

        # Warna titik: merah jika RED_ONLY, hijau jika GREEN_ONLY
        dot_color = (0, 0, 255) if "RED" in label else (0, 255, 0)
        cv2.circle(frame, (int(cx), int(cy)), 8, dot_color, -1)
        cv2.circle(frame, (int(cx), int(cy)), 8, white,      1)

        # Garis panduan oranye tetap tampil sebagai referensi
        cv2.line(frame, self.guide_p1, self.guide_p2, orange, 1)

        # ── Teks Info dihilangkan sesuai permintaan ──
