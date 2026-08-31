"""Kamera atas/bawah dan capture foto berdasarkan deteksi YOLO PIS."""

import threading
import time
import traceback

import cv2
import numpy as np

# Patch untuk TensorRT lama tanpa memicu FutureWarning dari hasattr(np, 'bool').
if 'bool' not in np.__dict__:
    np.bool = bool

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

import config


def class_name(names, class_id: int) -> str:
    """Baca nama kelas dari result.names pada Ultralytics lama maupun baru."""

    if isinstance(names, dict):
        return str(names.get(class_id, class_id))
    if isinstance(names, (list, tuple)) and 0 <= class_id < len(names):
        return str(names[class_id])
    return str(class_id)


class LatestFrameCamera:
    """Reader kamera independen; consumer hanya mengambil frame terbaru."""

    def __init__(self, capture, label: str) -> None:
        self.capture = capture
        self.label = label
        self.lock = threading.Lock()
        self.frame = None
        self.sequence = 0

    def start(self):
        threading.Thread(
            target=self._run,
            daemon=True,
            name=f"camera-{self.label}",
        ).start()
        return self

    def _run(self) -> None:
        while True:
            ok, frame = self.capture.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue
            with self.lock:
                self.frame = frame
                self.sequence += 1

    def latest(self):
        with self.lock:
            return self.sequence, self.frame


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
    def __init__(self, cam_atas, cam_bawah, model_path, photo_dir, store) -> None:
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

    # ─────────────────────────────────────────────────────────────────────────
    # Thread utama
    # ─────────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="vision").start()

    def _load_one_model(self, path):
        suffix = path.suffix.lower()
        if suffix not in {".engine", ".pt"}:
            raise ValueError(f"format model tidak didukung: {path}")
        print(f"[VISION] Memuat model: {path}")
        model = YOLO(str(path), task="detect") if suffix == ".engine" else YOLO(str(path))

        # Warm-up membuat error engine/device terlihat sebelum loop kamera.
        dummy = np.zeros((config.YOLO_IMGSZ, config.YOLO_IMGSZ, 3), dtype=np.uint8)
        result = model.predict(
            source=dummy,
            imgsz=config.YOLO_IMGSZ,
            conf=config.YOLO_CONF,
            device=config.YOLO_DEVICE,
            verbose=False,
        )[0]
        names = getattr(result, "names", None) or {}
        print(
            f"[VISION] Model siap ({suffix}); "
            f"classes={len(names) if hasattr(names, '__len__') else '?'}"
        )
        return model

    def _load_model(self):
        if YOLO is None:
            return None
        requested = self.model_path.expanduser().resolve()
        if not requested.exists():
            raise FileNotFoundError(f"model tidak ditemukan: {requested}")
        try:
            return self._load_one_model(requested)
        except Exception as engine_error:
            fallback = requested.with_suffix(".pt")
            if requested.suffix.lower() != ".engine" or not fallback.exists():
                raise
            print(f"[VISION] Engine gagal: {engine_error}")
            print(f"[VISION] Fallback PyTorch CUDA: {fallback}")
            return self._load_one_model(fallback)

    @staticmethod
    def _open_camera(source, label):
        backend = cv2.CAP_V4L2 if hasattr(cv2, "CAP_V4L2") else cv2.CAP_ANY
        camera = cv2.VideoCapture(source, backend)
        if not camera.isOpened():
            camera.release()
            camera = cv2.VideoCapture(source)
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
        camera.set(cv2.CAP_PROP_FPS, config.CAMERA_FPS)
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        print(
            f"[VISION] Kamera {label}: {source} | "
            f"opened={camera.isOpened()} | "
            f"{int(camera.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
            f"{int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT))} @ "
            f"{camera.get(cv2.CAP_PROP_FPS):.2f} FPS"
        )
        return camera

    def _run(self) -> None:
        try:
            model = self._load_model()
        except Exception as exc:
            model = None
            message = f"Vision model: {exc}"
            self.store.update({"lastError": message})
            print(f"[VISION] {message}")
            traceback.print_exc()

        if not model:
            print("[VISION] YOLO/model tidak tersedia; kamera tetap berjalan tanpa deteksi.")

        top = LatestFrameCamera(
            self._open_camera(self.cam_atas, "atas"), "atas"
        ).start()
        bottom = LatestFrameCamera(
            self._open_camera(self.cam_bawah, "bawah"), "bawah"
        ).start()
        last_top_sequence = -1
        last_top_error = 0.0

        while True:
            top_sequence, frame_atas = top.latest()
            _, frame_bawah = bottom.latest()

            if frame_atas is None:
                now = time.monotonic()
                if now - last_top_error >= 1.0:
                    err_img = np.zeros(
                        (config.CAMERA_HEIGHT, config.CAMERA_WIDTH, 3),
                        dtype=np.uint8,
                    )
                    cv2.putText(err_img, "ERROR: KAMERA ATAS!", (20, 120),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    self.store.publish_frame(err_img)
                    last_top_error = now
                time.sleep(0.01)
                continue

            # Jangan inferensi dua kali pada frame kamera atas yang sama.
            if top_sequence == last_top_sequence:
                time.sleep(0.002)
                continue
            last_top_sequence = top_sequence

            if model:
                self._detect(model, frame_atas, frame_bawah)
            else:
                err_img = np.zeros((240, 320, 3), dtype=np.uint8)
                cv2.putText(err_img, "ERROR: MODEL TIDAK TERSEDIA", (15, 120),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
                self.store.publish_frame(err_img)
            if config.VISION_LOOP_DELAY_SECONDS > 0:
                time.sleep(config.VISION_LOOP_DELAY_SECONDS)

    # ─────────────────────────────────────────────────────────────────────────
    # Hot-reload PID (dipanggil tiap frame, sangat ringan)
    # ─────────────────────────────────────────────────────────────────────────

    def _sync_pid_config(self, cfg: dict) -> None:
        """
        Cek apakah GUI menyimpan nilai PID baru (via store['pid_config']['_version']).

        Operasi ini sangat ringan: hanya membaca 1 integer dan membandingkannya.
        Tidak ada lock berat atau network call — hanya dict lookup Python biasa.
        Pembaruan aktual (bagian dalam if) hanya terjadi saat user klik SAVE di GUI.
        """
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
        vision_state = self.store.vision_snapshot()
        self._sync_pid_config(vision_state["pid_config"])
        snapshot = vision_state["detection"]
        result = model.predict(
            source=frame_atas,
            imgsz=config.YOLO_IMGSZ,
            conf=config.YOLO_CONF,
            device=config.YOLO_DEVICE,
            verbose=False,
        )[0]
        annotated_frame = result.plot()
        names = getattr(result, "names", None) or {}

        red_candidates   = []
        green_candidates = []

        for box in result.boxes:
            name      = class_name(names, int(box.cls[0])).lower()
            cx        = box.xywh[0][0].item()
            cy        = box.xywh[0][1].item()
            w         = box.xywh[0][2].item()
            h         = box.xywh[0][3].item()
            bbox_area = w * h

            # ── Misi foto: boxblue & boxgreen ────────────────────────────────
            if "blue" in name and not snapshot["foto_bawah_ready"]:
                if bbox_area >= 5000:
                    img_to_save = frame_bawah if frame_bawah is not None else frame_atas
                    cv2.imwrite(str(self.photo_dir / "bawah.jpg"), img_to_save)
                    self.store.update({
                        "detection": {"label": "BOXBLUE (LOCKED & SAVED)", "foto_bawah_ready": True}
                    })
                    self.store.publish_frame(annotated_frame)
                    return

            if "green" in name and not snapshot["foto_atas_ready"]:
                if bbox_area >= 5000:
                    cv2.imwrite(str(self.photo_dir / "atas.jpg"), frame_atas)
                    self.store.update({
                        "detection": {"label": "BOXGREEN (LOCKED & SAVED)", "foto_atas_ready": True}
                    })
                    self.store.publish_frame(annotated_frame)
                    return

            # ── Kumpulkan kandidat buoy merah ────────────────────────────────
            if "buoyred" in name and bbox_area >= self.red_min_area:
                red_candidates.append((bbox_area, cx, cy))

            # ── Kumpulkan kandidat buoy hijau ────────────────────────────────
            if "buoygreen" in name and bbox_area >= self.green_min_area:
                green_candidates.append((bbox_area, cx, cy))

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

        self.store.publish_frame(annotated_frame)

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

        if error > self.pid.deadband:
            direction = "KANAN->KIRI"
        elif error < -self.pid.deadband:
            direction = "KIRI->KANAN"
        else:
            direction = "LURUS"

        p, i_val = pid_terms["p"], pid_terms["i"]
        d, u     = pid_terms["d"], pid_terms["u"]
        info_lines = [
            f"MODE  : BOTH BUOY",
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

        info_lines = [
            f"MODE  : {label}",
            f"SERVO : {servo_pwm} us",
        ]
        for idx, text in enumerate(info_lines):
            y_pos = 16 + idx * 18
            cv2.putText(frame, text, (6, y_pos),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 0, 0), 3)
            cv2.putText(frame, text, (6, y_pos),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, orange,    1)
