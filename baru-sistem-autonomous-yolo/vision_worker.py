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
        self.servo_neutral: int = config.SERVO_NEUTRAL
        self.red_min_area:  int = config.RED_BUOY_MIN_AREA

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

    # ─────────────────────────────────────────────────────────────────────────
    # Thread utama
    # ─────────────────────────────────────────────────────────────────────────

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

        while True:
            ok_atas, frame_atas = top.read()
            ok_bawah, frame_bawah = bottom.read()

            if not ok_atas or not ok_bawah:
                err_img = np.zeros((240, 320, 3), dtype=np.uint8)
                cv2.putText(err_img, "ERROR: KAMERA TERPUTUS!", (20, 120),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                self.store.live_frame_bgr = err_img
                time.sleep(1.0)
                continue

            if model:
                self._detect(model, frame_atas, frame_bawah)
            else:
                err_img = np.zeros((240, 320, 3), dtype=np.uint8)
                cv2.putText(err_img, "ERROR: MODEL TIDAK TERSEDIA", (15, 120),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
                self.store.live_frame_bgr = err_img
            time.sleep(0.03)

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
        cfg     = self.store.data.get("pid_config", {})
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
        results  = model(frame_atas, verbose=False, conf=0.5)
        annotated_frame = results[0].plot()

        red_candidates = []

        for result in results:
            for box in result.boxes:
                name      = model.names[int(box.cls[0])].lower()
                cx        = box.xywh[0][0].item()
                cy        = box.xywh[0][1].item()
                w         = box.xywh[0][2].item()
                h         = box.xywh[0][3].item()
                bbox_area = w * h

                # ── Misi foto: boxblue & boxgreen ────────────────────────────
                if "blue" in name and not snapshot["foto_bawah_ready"]:
                    if bbox_area >= 5000:
                        img_to_save = frame_bawah if frame_bawah is not None else frame_atas
                        cv2.imwrite(str(self.photo_dir / "bawah.jpg"), img_to_save)
                        self.store.update({
                            "detection": {"label": "BOXBLUE (LOCKED & SAVED)", "foto_bawah_ready": True}
                        })
                        self.store.live_frame_bgr = annotated_frame
                        return

                if "green" in name and not snapshot["foto_atas_ready"]:
                    if bbox_area >= 5000:
                        cv2.imwrite(str(self.photo_dir / "atas.jpg"), frame_atas)
                        self.store.update({
                            "detection": {"label": "BOXGREEN (LOCKED & SAVED)", "foto_atas_ready": True}
                        })
                        self.store.live_frame_bgr = annotated_frame
                        return

                # ── Kumpulkan kandidat buoy merah ────────────────────────────
                if "buoyred" in name and bbox_area >= self.red_min_area:
                    red_candidates.append((bbox_area, cx, cy))

        # ── Buoy-following PID ────────────────────────────────────────────────
        if red_candidates:
            _, cx, cy            = max(red_candidates, key=lambda r: r[0])
            error, x_target      = self._compute_guide_error(cx, cy)
            servo_pwm, pid_terms = self.pid.compute(error)

            self.store.update({
                "buoy": {
                    "detected":  True,
                    "cx":        round(cx, 1),
                    "cy":        round(cy, 1),
                    "x_target":  round(x_target, 1),
                    "error_px":  round(error, 1),
                    "servo_pwm": servo_pwm,
                    "pid":       pid_terms,
                }
            })
            self._draw_guide_overlay(annotated_frame, cx, cy, x_target,
                                     error, servo_pwm, pid_terms)
        else:
            self.pid.reset()
            self.store.update({
                "buoy": {
                    "detected":  False,
                    "cx":        0, "cy": 0, "x_target": 0,
                    "error_px":  0.0,
                    "servo_pwm": self.servo_neutral,
                    "pid":       {"p": 0.0, "i": 0.0, "d": 0.0, "u": 0.0, "dt": 0.0},
                }
            })
            self._draw_guide_line(annotated_frame)

        self.store.live_frame_bgr = annotated_frame

    # ─────────────────────────────────────────────────────────────────────────
    # Kalkulasi garis panduan
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_guide_error(self, x_buoy: float, y_buoy: float):
        """
        Hitung error posisi buoy merah terhadap garis panduan oranye.

        Formula: X_target(Y) = m * Y + c
            m = (X2 - X1) / (Y2 - Y1)
            c = X1 - m * Y1

        Returns: (error, x_target)
            error positif = buoy di KANAN garis → belok kiri
            error negatif = buoy di KIRI  garis → belok kanan
        """
        x_target = self._m * y_buoy + self._c
        return x_buoy - x_target, x_target

    # ─────────────────────────────────────────────────────────────────────────
    # Overlay visual di frame kamera
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_guide_line(self, frame: np.ndarray) -> None:
        """Gambar garis panduan oranye saja (tanpa info buoy)."""
        cv2.line(frame, self.guide_p1, self.guide_p2, (0, 165, 255), 2)

    def _draw_guide_overlay(
        self,
        frame:     np.ndarray,
        cx:        float,
        cy:        float,
        x_target:  float,
        error:     float,
        servo_pwm: int,
        pid_terms: dict,
    ) -> None:
        """
        Gambar overlay lengkap:
          - Garis panduan oranye (P1 -> P2)
          - Titik TARGET (kuning) di garis
          - Titik BUOY   (merah)  aktual
          - Garis ERROR  (cyan)   antara keduanya
          - Teks info: error, PWM, dan rincian P/I/D
        """
        orange = (0, 165, 255)
        yellow = (0, 255, 255)
        red    = (0, 0, 255)
        cyan   = (255, 255, 0)
        white  = (255, 255, 255)

        ix_t = int(x_target)
        iy   = int(cy)
        ix_b = int(cx)

        cv2.line(frame, self.guide_p1, self.guide_p2, orange, 2)
        cv2.circle(frame, (ix_t, iy), 7, yellow, -1)
        cv2.circle(frame, (ix_t, iy), 7, white,   1)
        cv2.circle(frame, (ix_b, iy), 7, red, -1)
        cv2.circle(frame, (ix_b, iy), 7, white,  1)
        cv2.line(frame, (ix_t, iy), (ix_b, iy), cyan, 2)

        if error > self.pid.deadband:
            direction = "KANAN->KIRI"
        elif error < -self.pid.deadband:
            direction = "KIRI->KANAN"
        else:
            direction = "LURUS"

        p, i_val = pid_terms["p"], pid_terms["i"]
        d, u     = pid_terms["d"], pid_terms["u"]
        info_lines = [
            f"ERROR : {error:+.1f}px  [{direction}]",
            f"SERVO : {servo_pwm} us",
            f"P={p:+.1f}  I={i_val:+.1f}  D={d:+.1f}",
            f"u={u:+.1f}  dt={pid_terms['dt']*1000:.1f}ms",
        ]
        for idx, text in enumerate(info_lines):
            y_pos = 16 + idx * 18
            cv2.putText(frame, text, (6, y_pos),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 0, 0), 3)
            cv2.putText(frame, text, (6, y_pos),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, orange,    1)
