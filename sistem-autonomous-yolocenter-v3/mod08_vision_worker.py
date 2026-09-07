"""Kamera atas/bawah dan capture foto berdasarkan deteksi YOLO PIS."""

from __future__ import annotations

import base64
import copy
import queue
import threading
import time
from typing import Any

import cv2
import numpy as np

# Patch untuk bug kompatibilitas TensorRT dan versi NumPy terbaru
if not hasattr(np, 'bool'):
    np.bool = bool

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

import mod01_config as config
from mod03_robot_topic import (
    TOPIK_FRAME,
    TOPIK_PERINTAH_VISION,
    TOPIK_VISION,
    robot_topic,
)
from mod05_state_manager import state


def _perangkat_yolo(nilai: str):
    if nilai.lower() == "auto":
        return None
    try:
        return int(nilai)
    except ValueError:
        return nilai


class VisionPublisher:
    """Adapter state milik vision: hot ke topik, PID dari cold JSON."""

    def update(self, perubahan: dict[str, Any]) -> None:
        perubahan = copy.deepcopy(perubahan)
        perubahan.pop("pid_config", None)
        if perubahan:
            robot_topic.publikasi(TOPIK_VISION, perubahan)

    def cold_snapshot(self) -> dict[str, Any]:
        return state.baca()

    def tandai_foto(self, kamera: str, tersedia: bool) -> None:
        state.atur_status_foto(kamera, tersedia)

    def reset_status_foto(self) -> None:
        state.reset_status_foto()

    def set_live_frame(self, bingkai: np.ndarray) -> None:
        kualitas = max(35, min(config.LIVE_FRAME_JPEG_QUALITY, 95))
        berhasil, jpeg = cv2.imencode(".jpg", bingkai, [cv2.IMWRITE_JPEG_QUALITY, kualitas])
        if berhasil:
            robot_topic.publikasi(
                TOPIK_FRAME,
                {"jpeg": base64.b64encode(jpeg).decode("ascii")},
                dipertahankan=False,
            )




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

    def __init__(
        self,
        indeks: int,
        lebar: int = config.CAMERA_WIDTH,
        tinggi: int = config.CAMERA_HEIGHT,
    ) -> None:
        self._tangkap = cv2.VideoCapture(indeks)
        self._tangkap.set(cv2.CAP_PROP_FRAME_WIDTH,  lebar)
        self._tangkap.set(cv2.CAP_PROP_FRAME_HEIGHT, tinggi)

        # Paksa buffer kamera sekecil mungkin agar frame selalu fresh (tidak stale)
        self._tangkap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._bingkai: "np.ndarray | None" = None
        self._berhasil: bool              = False
        self._kunci                   = threading.Lock()
        self._berhenti                = threading.Event()

    def start(self) -> "ThreadedCamera":
        """Mulai thread background dan tunggu sampai frame pertama siap (maks 3 detik)."""
        threading.Thread(target=self._jalankan, daemon=True, name=f"cam-{id(self)}").start()
        batas_waktu = time.monotonic() + 3.0
        while time.monotonic() < batas_waktu:
            with self._kunci:
                if self._bingkai is not None:
                    return self
            time.sleep(0.05)
        return self

    def _jalankan(self) -> None:
        """Loop background: terus grab frame kamera tanpa henti."""
        while not self._berhenti.is_set():
            berhasil, bingkai = self._tangkap.read()
            with self._kunci:
                self._berhasil = berhasil
                self._bingkai  = bingkai
            # Yield agar GIL berpindah ke thread lain, tidak sleep lama
            time.sleep(0.001)

    def read(self) -> "tuple[bool, np.ndarray | None]":
        """Ambil frame terbaru dari buffer (< 1ms, tidak blocking hardware)."""
        with self._kunci:
            return self._berhasil, (self._bingkai.copy() if self._bingkai is not None else None)

    def release(self) -> None:
        """Hentikan thread dan lepas resource kamera."""
        self._berhenti.set()
        self._tangkap.release()

    @property
    def is_opened(self) -> bool:
        return self._tangkap.isOpened()


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
        batas_integral: float,
        zona_mati:      float,
        servo_netral:   int,
        servo_min:      int,
        servo_maks:     int,
    ) -> None:
        self.kp             = kp
        self.ki             = ki
        self.kd             = kd
        self.batas_integral = batas_integral
        self.zona_mati      = zona_mati
        self.servo_netral   = servo_netral
        self.servo_min      = servo_min
        self.servo_maks     = servo_maks

        # State internal PID
        self._integral:    float = 0.0
        self._galat_lama:  float = 0.0
        self._waktu_lama:  float = 0.0

    def reset(self) -> None:
        """Reset state PID — panggil saat buoy hilang atau gain berubah."""
        self._integral   = 0.0
        self._galat_lama = 0.0
        self._waktu_lama  = 0.0

    def compute(self, galat: float) -> tuple:
        """
        Hitung output PID dan konversi ke PWM servo.

        Returns
        -------
        servo_pwm : int   — nilai PWM servo dalam µs
        pid_terms : dict  — rincian tiap komponen PID (untuk debug/monitoring)
        """
        sekarang = time.monotonic()
        sampel_pertama = self._waktu_lama == 0.0
        selisih_waktu = 0.033 if sampel_pertama else sekarang - self._waktu_lama
        selisih_waktu = max(selisih_waktu, 0.001)
        self._waktu_lama = sekarang

        # Dead-band: jika error sangat kecil → anggap lurus, jangan koreksi
        if abs(galat) <= self.zona_mati:
            self._integral   = 0.0
            self._galat_lama = galat
            return self.servo_netral, {
                "p": 0.0, "i": 0.0, "d": 0.0, "u": 0.0, "dt": selisih_waktu
            }

        # Komponen Proporsional
        komponen_p = self.kp * galat

        # Komponen Integral dengan anti-windup
        self._integral += galat * selisih_waktu
        self._integral  = max(-self.batas_integral,
                              min(self.batas_integral, self._integral))
        komponen_i = self.ki * self._integral

        # Komponen Derivatif
        komponen_d = 0.0 if sampel_pertama else self.kd * (galat - self._galat_lama) / selisih_waktu
        self._galat_lama = galat

        # Output total
        keluaran = komponen_p + komponen_i + komponen_d
        pwm = self.servo_netral - keluaran
        pwm = int(max(self.servo_min, min(self.servo_maks, pwm)))

        rincian_pid = {
            "p":  round(komponen_p, 2),
            "i":  round(komponen_i, 2),
            "d":  round(komponen_d, 2),
            "u":  round(keluaran,   2),
            "dt": round(selisih_waktu, 4),
        }
        return pwm, rincian_pid


# ═════════════════════════════════════════════════════════════════════════════
# Vision Worker
# ═════════════════════════════════════════════════════════════════════════════

class VisionWorker:
    def __init__(self, kam_atas: int, kam_bawah: int, jalur_model, direktori_foto, penyimpan) -> None:
        self.kam_atas, self.kam_bawah = kam_atas, kam_bawah
        self.jalur_model, self.direktori_foto, self.penyimpan = jalur_model, direktori_foto, penyimpan

        # ── Parameter garis panduan oranye ───────────────────────────────────
        self.titik_panduan1: tuple = config.GUIDE_LINE_P1
        self.titik_panduan2: tuple = config.GUIDE_LINE_P2

        # ── Parameter servo ───────────────────────────────────────────────────
        self.servo_netral:        int = config.SERVO_NEUTRAL
        self.luas_min_merah:      int = config.RED_BUOY_MIN_AREA
        self.luas_min_hijau:      int = config.GREEN_BUOY_MIN_AREA
        self.pergeseran_pencarian: int = config.SERVO_SEARCH_OFFSET

        # ── PID Controller ────────────────────────────────────────────────────
        self.pid = BuoyPIDController(
            kp             = config.SERVO_KP,
            ki             = config.SERVO_KI,
            kd             = config.SERVO_KD,
            batas_integral = config.SERVO_INTEGRAL_LIMIT,
            zona_mati      = config.SERVO_DEADBAND,
            servo_netral   = config.SERVO_NEUTRAL,
            servo_min      = config.SERVO_MIN,
            servo_maks     = config.SERVO_MAX,
        )

        # ── Prakalkulasi gradien garis panduan ───────────────────────────────
        x1, y1 = self.titik_panduan1
        x2, y2 = self.titik_panduan2
        if y2 != y1:
            self._m = (x2 - x1) / (y2 - y1)
            self._c = x1 - self._m * y1
        else:
            self._m = 0.0
            self._c = (x1 + x2) / 2.0

        # ── Cache cold state ───────────────────────────────────────────────────
        self._versi_pid_terakhir: int = 0
        self._waktu_baca_cold = 0.0
        self._cache_cold: dict[str, Any] = {}
        self._perintah_foto = queue.SimpleQueue()
        self.perangkat_yolo = _perangkat_yolo(config.YOLO_DEVICE)

        # ── FPS Tracking ──────────────────────────────────────────────────────
        self._riwayat_fps = []
        self._waktu_frame_terakhir = time.monotonic()

    # ─────────────────────────────────────────────────────────────────────────
    # Thread utama
    # ─────────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        threading.Thread(target=self._jalankan, daemon=True, name="vision").start()

    def _jalankan(self) -> None:
        robot_topic.berlangganan(TOPIK_PERINTAH_VISION, self._terima_perintah_foto)
        for kamera in ("atas", "bawah"):
            tersedia = (self.direktori_foto / f"{kamera}.jpg").is_file()
            self.penyimpan.tandai_foto(kamera, tersedia)

        # ── Muat model YOLO ───────────────────────────────────────────────────
        model = None
        tipe_model = "NONE"
        if YOLO:
            jalur_engine = self.jalur_model.with_suffix('.engine')
            jalur_pt     = self.jalur_model.with_suffix('.pt')
            if jalur_engine.exists():
                try:
                    model = YOLO(str(jalur_engine), task="detect")
                    tipe_model = "TensorRT (.engine) — GPU"
                except Exception as galat:
                    print(f"[VISION] Model TensorRT gagal dimuat: {galat}")
                    print("[VISION] Mencoba fallback model PyTorch.")
            if model is None and jalur_pt.exists():
                model = YOLO(str(jalur_pt))
                tipe_model = "PyTorch (.pt) — CPU/GPU"
            if model is not None:
                print(f"[VISION] ✓ Model {tipe_model} berhasil dimuat")
                print(
                    f"[VISION]   → device={config.YOLO_DEVICE}, "
                    f"imgsz={config.YOLO_IMAGE_SIZE}"
                )

        if model is None:
            print("[VISION] ✗ YOLO/model tidak tersedia; kamera tetap berjalan tanpa deteksi.")
        else:
            print(
                f"[VISION] Pipeline siap: ThreadedCamera × 2 | YOLO {tipe_model} | "
                f"device={config.YOLO_DEVICE} | imgsz={config.YOLO_IMAGE_SIZE}"
            )

        # ── Inisialisasi ThreadedCamera (non-blocking, masing-masing thread sendiri) ──
        # ThreadedCamera.start() menunggu frame pertama siap (maks 3 detik)
        # sehingga loop inferensi di bawah tidak langsung menerima None.
        print("[VISION] Menginisialisasi kamera atas (ThreadedCamera)...")
        kamera_atas = ThreadedCamera(self.kam_atas).start()
        print("[VISION] Menginisialisasi kamera bawah (ThreadedCamera)...")
        kamera_bawah = ThreadedCamera(self.kam_bawah).start()
        print("[VISION] Kedua kamera siap — memulai loop inferensi tanpa blocking.")

        try:
            while True:
                # Ambil frame dari buffer (< 1ms, tidak menunggu hardware)
                ok_atas,  bingkai_atas  = kamera_atas.read()
                ok_bawah, bingkai_bawah = kamera_bawah.read()

                if not ok_atas or not ok_bawah:
                    gambar_galat = np.zeros(
                        (config.CAMERA_HEIGHT, config.CAMERA_WIDTH, 3),
                        dtype=np.uint8,
                    )
                    cv2.putText(gambar_galat, "ERROR: KAMERA TERPUTUS!", (20, 240),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    self.penyimpan.set_live_frame(gambar_galat)
                    time.sleep(1.0)
                    continue

                self._proses_perintah_foto(bingkai_atas, bingkai_bawah)

                if model is not None:
                    self._deteksi(model, bingkai_atas, bingkai_bawah)
                else:
                    gambar_galat = np.zeros(
                        (config.CAMERA_HEIGHT, config.CAMERA_WIDTH, 3),
                        dtype=np.uint8,
                    )
                    cv2.putText(gambar_galat, "ERROR: MODEL TIDAK TERSEDIA", (15, 240),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
                    self.penyimpan.set_live_frame(gambar_galat)

                # Throttle minimal: cegah 100% CPU usage, tapi tidak membatasi FPS
                # seperti sleep(0.03) yang lama. Inferensi YOLO sudah jadi rate-limiter
                # alami (15–50ms per frame tergantung model).
                time.sleep(0.001)
        finally:
            # Pastikan resource kamera dilepas saat thread berhenti
            kamera_atas.release()
            kamera_bawah.release()
            print("[VISION] Kamera dilepas (ThreadedCamera released).")

    def _terima_perintah_foto(self, _topik: str, perintah: Any) -> None:
        if not isinstance(perintah, dict):
            return
        if perintah.get("command") not in {"tahan_foto", "foto_sekarang", "reset_foto"}:
            return
        self._perintah_foto.put(copy.deepcopy(perintah))

    def _proses_perintah_foto(self, bingkai_atas, bingkai_bawah) -> None:
        while True:
            try:
                perintah = self._perintah_foto.get_nowait()
            except queue.Empty:
                return

            nama = perintah["command"]
            self._waktu_baca_cold = 0.0

            if nama == "tahan_foto":
                continue

            if nama == "reset_foto":
                for kamera in ("atas", "bawah"):
                    (self.direktori_foto / f"{kamera}.jpg").unlink(missing_ok=True)
                self.penyimpan.reset_status_foto()
                self.penyimpan.update({"detection": {"label": "FOTO DIRESET"}})
                continue

            kamera = perintah.get("kamera")
            if kamera not in {"atas", "bawah"}:
                continue
            if self.penyimpan.cold_snapshot().get("tahan_foto", False):
                self.penyimpan.update({"detection": {"label": "FOTO DITAHAN"}})
                continue

            gambar = bingkai_atas if kamera == "atas" else bingkai_bawah
            if gambar is None:
                continue
            self.direktori_foto.mkdir(parents=True, exist_ok=True)
            if cv2.imwrite(str(self.direktori_foto / f"{kamera}.jpg"), gambar):
                self.penyimpan.tandai_foto(kamera, True)
                self.penyimpan.update({
                    "detection": {"label": f"FOTO {kamera.upper()} DISIMPAN MANUAL"}
                })

    # ─────────────────────────────────────────────────────────────────────────
    # Hot-reload PID (dipanggil tiap frame, sangat ringan)
    # ─────────────────────────────────────────────────────────────────────────

    def _baca_cold_berkala(self) -> dict[str, Any]:
        sekarang = time.monotonic()
        if sekarang - self._waktu_baca_cold >= 0.25 or not self._cache_cold:
            self._cache_cold = self.penyimpan.cold_snapshot()
            self._waktu_baca_cold = sekarang
        return self._cache_cold

    def _sinkron_konfig_pid(self, konfig: dict[str, Any]) -> None:
        """
        Terapkan PID dari cache cold state ketika nomor versinya berubah.
        """
        versi   = konfig.get("_version", 0)

        if versi == self._versi_pid_terakhir:
            return   # Tidak ada perubahan → langsung kembali (< 1 µs)

        # ── Perubahan terdeteksi: terapkan gain baru ──────────────────────────
        self._versi_pid_terakhir = versi
        self.pid.kp             = float(konfig.get("kp",             self.pid.kp))
        self.pid.ki             = float(konfig.get("ki",             self.pid.ki))
        self.pid.kd             = float(konfig.get("kd",             self.pid.kd))
        self.pid.batas_integral = float(konfig.get("integral_limit", self.pid.batas_integral))
        self.pid.zona_mati      = float(konfig.get("deadband",       self.pid.zona_mati))

        # Reset state internal agar tidak ada carry-over dari nilai lama
        self.pid.reset()

        print(
            f"[VISION] PID hot-reload v{versi}: "
            f"Kp={self.pid.kp}  Ki={self.pid.ki}  Kd={self.pid.kd}  "
            f"DB={self.pid.zona_mati}  ILim={self.pid.batas_integral}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Deteksi utama
    # ─────────────────────────────────────────────────────────────────────────

    def _deteksi(self, model, bingkai_atas, bingkai_bawah) -> None:
        data_cold = self._baca_cold_berkala()
        self._sinkron_konfig_pid(data_cold["pid_config"])

        status_foto = data_cold["foto"]
        tahan_foto = bool(data_cold.get("tahan_foto", False))
        foto_atas_siap = bool(status_foto["atas"]["tersedia"])
        foto_bawah_siap = bool(status_foto["bawah"]["tersedia"])
        opsi_inferensi = {
            "verbose": False,
            "conf": config.YOLO_CONFIDENCE,
            "imgsz": config.YOLO_IMAGE_SIZE,
            "agnostic_nms": True,
        }
        if self.perangkat_yolo is not None:
            opsi_inferensi["device"] = self.perangkat_yolo
        # Kamera atas adalah sumber seluruh deteksi YOLO. Kamera bawah tidak
        # dideteksi; frame-nya diambil sebagai bukti ketika boxblue terlihat.
        hasil_deteksi = model(bingkai_atas, **opsi_inferensi)
        
        # Optimasi CPU: Jangan gunakan results[0].plot() bawaan YOLO yang berat. 
        # Kita gambar (copy) frame asli, lalu gambar kotak manual.
        bingkai_terannotasi = bingkai_atas.copy()

        kandidat_merah  = []
        kandidat_hijau  = []
        # Tracking area terbesar boxgreen/boxblue per frame (untuk status GUI)
        luas_terbaik_hijau = 0
        luas_terbaik_biru  = 0

        for hasil in hasil_deteksi:
            for kotak in hasil.boxes:
                nama        = model.names[int(kotak.cls[0])].lower()
                pos_x       = kotak.xywh[0][0].item()
                pos_y       = kotak.xywh[0][1].item()
                lebar_kotak = kotak.xywh[0][2].item()
                tinggi_kotak= kotak.xywh[0][3].item()
                luas_kotak  = lebar_kotak * tinggi_kotak

                # ── Filter Aspek Rasio untuk membedakan Box dan Buoy ─────────
                # Jika objek terdeteksi sebagai "box" tapi bentuk bounding box-nya
                # sangat jangkung/berdiri (tinggi jauh lebih besar dari lebar),
                # kemungkinan besar itu adalah buoy yang salah klasifikasi.
                if ("blue" in nama or "green" in nama) and not "buoy" in nama:
                    if tinggi_kotak > lebar_kotak * config.BOX_MAX_HEIGHT_RATIO:
                        continue  # Abaikan salah deteksi ini (anggap bukan box)

                # --- Gambar Bounding Box Ringan (Manual) ---
                x1 = int(pos_x - lebar_kotak / 2)
                y1 = int(pos_y - tinggi_kotak / 2)
                x2 = int(pos_x + lebar_kotak / 2)
                y2 = int(pos_y + tinggi_kotak / 2)
                
                warna = (0, 0, 255) if "red" in nama else (0, 255, 0) if "green" in nama else (255, 0, 0)
                cv2.rectangle(bingkai_terannotasi, (x1, y1), (x2, y2), warna, 2)
                cv2.putText(bingkai_terannotasi, nama, (x1, max(15, y1 - 5)), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, warna, 1)
                # -------------------------------------------

                # ── Misi foto: boxblue & boxgreen ────────────────────────────
                if "blue" in nama and not "buoy" in nama:
                    luas_terbaik_biru = max(luas_terbaik_biru, int(luas_kotak))
                    if not tahan_foto and not foto_bawah_siap and luas_kotak >= config.BOX_PHOTO_MIN_AREA:
                        # Trigger berasal dari deteksi kamera atas, sedangkan
                        # gambar yang wajib disimpan berasal dari kamera bawah.
                        gambar_disimpan = bingkai_bawah if bingkai_bawah is not None else bingkai_atas
                        if not cv2.imwrite(str(self.direktori_foto / "bawah.jpg"), gambar_disimpan):
                            continue
                        self.penyimpan.tandai_foto("bawah", True)
                        self._waktu_baca_cold = 0.0
                        self.penyimpan.update({
                            "detection": {
                                "label": "BOXBLUE (LOCKED & SAVED)",
                                "area_blue": int(luas_kotak),
                            }
                        })
                        self.penyimpan.set_live_frame(bingkai_terannotasi)
                        return

                if "green" in nama and not "buoy" in nama:
                    luas_terbaik_hijau = max(luas_terbaik_hijau, int(luas_kotak))
                    if not tahan_foto and not foto_atas_siap and luas_kotak >= config.BOX_PHOTO_MIN_AREA:
                        if not cv2.imwrite(str(self.direktori_foto / "atas.jpg"), bingkai_atas):
                            continue
                        self.penyimpan.tandai_foto("atas", True)
                        self._waktu_baca_cold = 0.0
                        self.penyimpan.update({
                            "detection": {
                                "label": "BOXGREEN (LOCKED & SAVED)",
                                "area_green": int(luas_kotak),
                            }
                        })
                        self.penyimpan.set_live_frame(bingkai_terannotasi)
                        return

                # ── Kumpulkan kandidat buoy merah ────────────────────────────
                if "buoyred" in nama and luas_kotak >= self.luas_min_merah:
                    kandidat_merah.append((luas_kotak, pos_x, pos_y))

                # ── Kumpulkan kandidat buoy hijau ────────────────────────────
                if "buoygreen" in nama and luas_kotak >= self.luas_min_hijau:
                    kandidat_hijau.append((luas_kotak, pos_x, pos_y))

        # Publikasikan setiap frame agar area lama kembali nol saat objek hilang.
        if luas_terbaik_biru > 0:
            label_deteksi = f"BOXBLUE terdeteksi ({luas_terbaik_biru:,} px²)"
        elif luas_terbaik_hijau > 0:
            label_deteksi = f"BOXGREEN terdeteksi ({luas_terbaik_hijau:,} px²)"
        else:
            label_deteksi = "STANDBY"
        self.penyimpan.update({
            "detection": {
                "label": label_deteksi,
                "area_green": luas_terbaik_hijau,
                "area_blue": luas_terbaik_biru,
            }
        })

        # ── Pilih buoy terdekat (bbox area terbesar) dari masing-masing warna ──
        merah_terbaik = max(kandidat_merah, key=lambda r: r[0]) if kandidat_merah else None
        hijau_terbaik = max(kandidat_hijau, key=lambda r: r[0]) if kandidat_hijau else None

        # ── Buoy-following: 4 kondisi ─────────────────────────────────────────
        if merah_terbaik and hijau_terbaik:
            # ── KONDISI 1: Kedua buoy terdeteksi → koreksi ke titik tengah ───
            pos_x_tengah = (merah_terbaik[1] + hijau_terbaik[1]) / 2.0
            pos_y_tengah = (merah_terbaik[2] + hijau_terbaik[2]) / 2.0
            galat, x_target            = self._hitung_galat_panduan(pos_x_tengah, pos_y_tengah)
            servo_pwm, rincian_pid = self.pid.compute(galat)

            self.penyimpan.update({
                "buoy": {
                    "detected":   True,
                    "mode":       "BOTH",
                    "cx":         round(pos_x_tengah,      1),
                    "cy":         round(pos_y_tengah,      1),
                    "cx_red":     round(merah_terbaik[1], 1),
                    "cx_green":   round(hijau_terbaik[1], 1),
                    "x_target":   round(x_target,        1),
                    "error_px":   round(galat,           1),
                    "servo_pwm":  servo_pwm,
                    "pid":        rincian_pid,
                }
            })
            self._gambar_overlay_gerbang(bingkai_terannotasi, merah_terbaik, hijau_terbaik,
                                        pos_x_tengah, pos_y_tengah, x_target, galat, servo_pwm, rincian_pid)

        elif merah_terbaik and not hijau_terbaik:
            # ── KONDISI 2: Hanya buoyred → belok KANAN cari buoygreen ────────
            self.pid.reset()
            servo_pwm = min(self.servo_netral + self.pergeseran_pencarian, self.pid.servo_maks)
            self.penyimpan.update({
                "buoy": {
                    "detected":  True,
                    "mode":      "RED_ONLY",
                    "cx":        round(merah_terbaik[1], 1),
                    "cy":        round(merah_terbaik[2], 1),
                    "cx_red":    round(merah_terbaik[1], 1),
                    "cx_green":  0,
                    "x_target":  0,
                    "error_px":  0.0,
                    "servo_pwm": servo_pwm,
                    "pid":       {"p": 0.0, "i": 0.0, "d": 0.0, "u": 0.0, "dt": 0.0},
                }
            })
            self._gambar_overlay_pencarian(bingkai_terannotasi, merah_terbaik[1], merah_terbaik[2],
                                           "ONLY RED -> SEARCH RIGHT", servo_pwm)

        elif hijau_terbaik and not merah_terbaik:
            # ── KONDISI 3: Hanya buoygreen → belok KIRI cari buoyred ─────────
            self.pid.reset()
            servo_pwm = max(self.servo_netral - self.pergeseran_pencarian, self.pid.servo_min)
            self.penyimpan.update({
                "buoy": {
                    "detected":  True,
                    "mode":      "GREEN_ONLY",
                    "cx":        round(hijau_terbaik[1], 1),
                    "cy":        round(hijau_terbaik[2], 1),
                    "cx_red":    0,
                    "cx_green":  round(hijau_terbaik[1], 1),
                    "x_target":  0,
                    "error_px":  0.0,
                    "servo_pwm": servo_pwm,
                    "pid":       {"p": 0.0, "i": 0.0, "d": 0.0, "u": 0.0, "dt": 0.0},
                }
            })
            self._gambar_overlay_pencarian(bingkai_terannotasi, hijau_terbaik[1], hijau_terbaik[2],
                                           "ONLY GREEN -> SEARCH LEFT", servo_pwm)

        else:
            # ── KONDISI 4: Tidak ada buoy → servo diam di neutral ─────────────
            self.pid.reset()
            self.penyimpan.update({
                "buoy": {
                    "detected":  False,
                    "mode":      "NONE",
                    "cx":        0, "cy": 0, "x_target": 0,
                    "cx_red":    0, "cx_green": 0,
                    "error_px":  0.0,
                    "servo_pwm": self.servo_netral,
                    "pid":       {"p": 0.0, "i": 0.0, "d": 0.0, "u": 0.0, "dt": 0.0},
                }
            })
            self._gambar_garis_panduan(bingkai_terannotasi)
        # ── Hitung dan Tampilkan FPS ──────────────────────────────────────────
        sekarang = time.monotonic()
        selisih_waktu = sekarang - self._waktu_frame_terakhir
        self._waktu_frame_terakhir = sekarang
        fps = 1.0 / selisih_waktu if selisih_waktu > 0 else 0.0

        self._riwayat_fps.append(fps)
        if len(self._riwayat_fps) > 15:
            self._riwayat_fps.pop(0)
        rata_rata_fps = sum(self._riwayat_fps) / len(self._riwayat_fps)

        posisi_fps = (config.CAMERA_WIDTH - 90, 20)
        cv2.putText(bingkai_terannotasi, f"FPS: {rata_rata_fps:.1f}", posisi_fps,
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        self.penyimpan.set_live_frame(bingkai_terannotasi)

    # ─────────────────────────────────────────────────────────────────────────
    # Kalkulasi garis panduan
    # ─────────────────────────────────────────────────────────────────────────

    def _hitung_galat_panduan(self, pos_x_buoy: float, pos_y_buoy: float):
        """
        Hitung error posisi (midpoint buoy atau buoy tunggal) terhadap garis panduan oranye.

        Formula: X_target(Y) = m * Y + c
            m = (X2 - X1) / (Y2 - Y1)
            c = X1 - m * Y1

        Returns: (error, x_target)
            error positif = target di KANAN garis → belok kiri
            error negatif = target di KIRI  garis → belok kanan
        """
        pos_x_target = self._m * pos_y_buoy + self._c
        return pos_x_buoy - pos_x_target, pos_x_target

    # ─────────────────────────────────────────────────────────────────────────
    # Overlay visual di frame kamera
    # ─────────────────────────────────────────────────────────────────────────

    def _gambar_garis_panduan(self, bingkai: np.ndarray) -> None:
        """Gambar garis panduan oranye saja (tanpa info buoy)."""
        cv2.line(bingkai, self.titik_panduan1, self.titik_panduan2, (0, 165, 255), 2)

    def _gambar_overlay_gerbang(
        self,
        bingkai:         np.ndarray,
        merah_terbaik:  tuple,
        hijau_terbaik:  tuple,
        pos_x_tengah:   float,
        pos_y_tengah:   float,
        pos_x_target:   float,
        galat:          float,
        servo_pwm:      int,
        rincian_pid:    dict,
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
        oranye = (0, 165, 255)
        kuning = (0, 255, 255)
        hijau  = (0, 255, 0)
        merah  = (0, 0, 255)
        sian   = (255, 255, 0)
        putih  = (255, 255, 255)

        int_x_merah  = int(merah_terbaik[1]); int_y_merah  = int(merah_terbaik[2])
        int_x_hijau  = int(hijau_terbaik[1]); int_y_hijau  = int(hijau_terbaik[2])
        int_x_tengah = int(pos_x_tengah);     int_y_tengah = int(pos_y_tengah)
        int_x_target = int(pos_x_target)

        # Garis panduan oranye (referensi)
        cv2.line(bingkai, self.titik_panduan1, self.titik_panduan2, oranye, 1)

        # Garis gate merah–hijau
        cv2.line(bingkai, (int_x_merah, int_y_merah), (int_x_hijau, int_y_hijau), putih, 2)

        # Titik buoy merah
        cv2.circle(bingkai, (int_x_merah, int_y_merah), 8, merah, -1)
        cv2.circle(bingkai, (int_x_merah, int_y_merah), 8, putih,  1)

        # Titik buoy hijau
        cv2.circle(bingkai, (int_x_hijau, int_y_hijau), 8, hijau, -1)
        cv2.circle(bingkai, (int_x_hijau, int_y_hijau), 8, putih,  1)

        # Titik midpoint (kuning)
        cv2.circle(bingkai, (int_x_tengah, int_y_tengah), 7, kuning, -1)
        cv2.circle(bingkai, (int_x_tengah, int_y_tengah), 7, putih,   1)

        # Titik target di garis panduan (oranye terang)
        cv2.circle(bingkai, (int_x_target, int_y_tengah), 5, oranye, -1)

        # Garis error cyan
        cv2.line(bingkai, (int_x_target, int_y_tengah), (int_x_tengah, int_y_tengah), sian, 2)

        # ── Teks Info dihilangkan sesuai permintaan (hanya menyisakan visual garis) ──
        # Teks FPS tetap akan muncul karena digambar terpisah di akhir _detect

    def _gambar_overlay_pencarian(
        self,
        bingkai:    np.ndarray,
        pos_x:      float,
        pos_y:      float,
        label:      str,
        servo_pwm:  int,
    ) -> None:
        """
        Overlay kondisi SEARCH (hanya satu buoy terdeteksi):
          - Titik buoy yang terdeteksi
          - Teks mode + arah pencarian + nilai servo
        """
        oranye = (0, 165, 255)
        putih  = (255, 255, 255)

        # Warna titik: merah jika RED_ONLY, hijau jika GREEN_ONLY
        warna_titik = (0, 0, 255) if "RED" in label else (0, 255, 0)
        cv2.circle(bingkai, (int(pos_x), int(pos_y)), 8, warna_titik, -1)
        cv2.circle(bingkai, (int(pos_x), int(pos_y)), 8, putih,        1)

        # Garis panduan oranye tetap tampil sebagai referensi
        cv2.line(bingkai, self.titik_panduan1, self.titik_panduan2, oranye, 1)

        # ── Teks Info dihilangkan sesuai permintaan ──


def main() -> None:
    config.PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    robot_topic.mulai()
    penerbit = VisionPublisher()
    VisionWorker(
        config.CAM_ATAS_INDEX,
        config.CAM_BAWAH_INDEX,
        config.MODEL_PATH,
        config.PHOTO_DIR,
        penerbit,
    )._jalankan()


if __name__ == "__main__":
    main()
