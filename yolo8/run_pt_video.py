from __future__ import annotations

import argparse
import json
import platform
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

import cv2

from buoy_pairing import buoy_color, frontmost_pair, pair_buoys
from pixel_distance import average_valid_distances, estimate_camera_distance_m


# SATU-SATUNYA pengaturan orientasi lintasan.
#
# PENTING -- jangan tafsirkan sebagai separuh kanan/kiri GAMBAR:
#   "right" = buoy HIJAU harus berada di kanan buoy MERAH dalam satu pasangan.
#   "left"  = buoy HIJAU harus berada di kiri buoy MERAH dalam satu pasangan.
#
# Midpoint pasangan boleh berada di mana pun dalam frame. Pemilihan target
# terdekat selalu dilakukan secara global dari posisi dasar bbox paling bawah.
FOCUS_SIDE = "right"


def selected_backend(requested: str) -> str:
    """Pilih CUDA otomatis pada Linux ARM64 (Jetson), DirectML selain itu."""

    if requested != "auto":
        return requested
    machine = platform.machine().lower()
    if sys.platform.startswith("linux") and machine in {"aarch64", "arm64"}:
        return "cuda"
    return "directml"


def create_inference_engine(args):
    """Lazy import agar Jetson tidak perlu menginstal ONNX Runtime DirectML."""

    backend = selected_backend(args.backend)
    if backend == "cuda":
        from cuda_engine import YOLOCuda

        engine_class = YOLOCuda
    else:
        from run_pt import YOLODirectML

        engine_class = YOLODirectML

    print(f"[ENGINE] Selected backend: {backend}")
    return engine_class(
        args.model,
        imgsz=args.imgsz,
        conf=args.conf,
        iou=args.iou,
        cpu=args.cpu,
        force_export=args.force_export,
    )


def open_video_source(video: str | None, gstreamer: str | None):
    """Buka file, USB camera index, atau pipeline GStreamer/CSI Jetson."""

    if gstreamer:
        capture = cv2.VideoCapture(gstreamer, cv2.CAP_GSTREAMER)
        return capture, "gstreamer", "gstreamer"

    if video is None:
        raise ValueError("Berikan path video, camera ID, atau --gstreamer")

    candidate = Path(video).expanduser()
    if candidate.is_file():
        capture = cv2.VideoCapture(str(candidate))
        return capture, str(candidate), candidate.stem

    try:
        camera_id = int(video)
    except ValueError as exc:
        raise FileNotFoundError(f"Video tidak ditemukan: {candidate}") from exc

    capture = cv2.VideoCapture(camera_id, cv2.CAP_V4L2)
    if not capture.isOpened():
        capture.release()
        capture = cv2.VideoCapture(camera_id)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture, f"camera:{camera_id}", f"camera_{camera_id}"


# ============================================================================
# LOW LATENCY WEBSOCKET
# ============================================================================
#
# WebSocket digunakan untuk mengirim DATA BUOY TERBARU ke sistem autonomous.
#
# Tidak ada:
#
#   - timestamp
#   - QoS
#   - history
#   - queue panjang
#
# Sistem menggunakan prinsip:
#
#       LATEST STATE ONLY
#
# Contoh:
#
#   frame 100 -> data A
#   frame 101 -> data B
#   frame 102 -> data C
#
# Kalau network belum selesai mengirim A ketika C sudah tersedia,
# data lama tidak perlu dipertahankan.
#
# Autonomous system lebih membutuhkan:
#
#       DATA TERBARU
#
# daripada:
#
#       SEMUA DATA TAPI TERLAMBAT
#
# TCP_NODELAY juga digunakan untuk menghindari Nagle buffering sehingga packet
# kecil tidak sengaja ditahan untuk digabung dengan packet berikutnya.
# ============================================================================


class LowLatencyWebSocketSender:
    """WebSocket sender asynchronous dengan latest-state-only."""

    def __init__(self, url: str):
        self.url = url
        self.latest_message: str | None = None
        self.condition = threading.Condition()
        self.running = True
        self.connected = False
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def send(self, payload: dict):
        """Ganti message lama dengan state terbaru."""

        message = json.dumps(payload, separators=(",", ":"))

        with self.condition:
            self.latest_message = message
            self.condition.notify()

    def _connect(self):
        # Import websocket hanya kalau fitur WebSocket benar-benar digunakan.
        #
        # Jadi tanpa --ws-url package websocket-client tidak diperlukan.
        try:
            import websocket
        except ImportError as exc:
            raise RuntimeError(
                "WebSocket aktif tetapi websocket-client belum terinstall.\n"
                "Install dengan:\n"
                "python -m pip install websocket-client"
            ) from exc

        ws = websocket.create_connection(
            self.url,
            timeout=1.0,
            enable_multithread=True,
        )

        # Matikan Nagle algorithm untuk mengurangi latency packet kecil.
        try:
            ws.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except (AttributeError, OSError):
            pass

        return ws

    def _worker(self):
        ws = None

        while self.running:
            # ----------------------------------------------------------------
            # CONNECT / RECONNECT
            # ----------------------------------------------------------------

            if ws is None:
                try:
                    ws = self._connect()

                    if not self.connected:
                        print(f"\n[WS] Connected: {self.url}")

                    self.connected = True

                except Exception:
                    if self.connected:
                        print("\n[WS] Connection lost.")

                    self.connected = False

                    # Hanya worker network yang menunggu.
                    # YOLO inference tidak ikut ter-block.
                    time.sleep(0.2)
                    continue

            # ----------------------------------------------------------------
            # TUNGGU STATE TERBARU
            # ----------------------------------------------------------------

            with self.condition:
                while self.latest_message is None and self.running:
                    self.condition.wait(timeout=0.2)

                if not self.running:
                    break

                message = self.latest_message
                self.latest_message = None

            # ----------------------------------------------------------------
            # SEND
            # ----------------------------------------------------------------

            try:
                ws.send(message)

            except Exception:
                # Message yang gagal tidak dimasukkan kembali.
                #
                # Kalau connection drop, message itu kemungkinan sudah stale.
                # Setelah reconnect kita hanya ingin state terbaru.
                try:
                    ws.close()
                except Exception:
                    pass

                ws = None
                self.connected = False

        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def close(self):
        self.running = False

        with self.condition:
            self.condition.notify_all()

        self.thread.join(timeout=1.0)


# ============================================================================
# TKINTER CALIBRATION PANEL
# ============================================================================
#
# Panel ini OPTIONAL.
#
# Aktifkan:
#
#   --calibration-ui
#
# Slider:
#
#   Known Object Width
#       panjang/lebar nyata buoy dalam centimeter
#
#   Camera Focal Length
#       focal length horizontal kamera dalam pixel
#
# Nilai slider dibaca LANGSUNG setiap frame.
#
# Jadi user dapat menggeser slider ketika video sedang berjalan:
#
#       slider berubah
#           |
#           v
#       parameter pixel-distance berubah
#           |
#           +------> overlay distance
#           |
#           +------> WebSocket distance
#
# Tidak perlu:
#
#   restart
#   reload model
#   restart video
#
# Tkinter sengaja tidak di-import secara global.
#
# Kalau --calibration-ui tidak digunakan, script tidak menyentuh Tkinter.
# ============================================================================


class CalibrationUI:
    """Panel live untuk panjang object dan focal length pixel."""

    def __init__(
        self,
        object_width_cm: float,
        focal_length_px: float,
    ):
        # Lazy import supaya Tkinter hanya diperlukan ketika UI digunakan.
        try:
            import tkinter as tk
        except ImportError as exc:
            raise RuntimeError(
                "Calibration UI membutuhkan Tkinter.\n"
                "Windows Python biasanya sudah menyertakan Tkinter.\n"
                "Linux/Jetson biasanya: sudo apt install python3-tk"
            ) from exc

        self.tk = tk

        # Cache nilai terakhir.
        #
        # Cache diperlukan karena user bisa menutup window Tkinter sementara
        # video masih terus berjalan.
        self.object_width_cm = object_width_cm
        self.focal_length_px = focal_length_px
        self.root = tk.Tk()

        self.root.title("YOLO Pixel Distance Parameters")
        self.root.geometry("480x260")
        self.root.resizable(True, False)

        # --------------------------------------------------------------------
        # VARIABLE TKINTER
        # --------------------------------------------------------------------

        self.distance_var = tk.DoubleVar(value=object_width_cm)
        self.width_var = tk.DoubleVar(value=focal_length_px)

        # --------------------------------------------------------------------
        # KNOWN OBJECT WIDTH (CM)
        # --------------------------------------------------------------------
        #
        # Range 1 sampai 200 cm untuk ukuran nyata object target.
        # --------------------------------------------------------------------

        tk.Label(
            self.root,
            text="Known Object Width (centimeter)",
            font=("Arial", 11, "bold"),
        ).pack(padx=10, pady=(12, 0), anchor="w")

        self.distance_scale = tk.Scale(
            self.root,
            from_=1.0,
            to=200.0,
            resolution=0.5,
            orient=tk.HORIZONTAL,
            variable=self.distance_var,
            length=450,
            showvalue=True,
        )

        self.distance_scale.pack(padx=10, fill="x")

        # --------------------------------------------------------------------
        # CAMERA FOCAL LENGTH (PX)
        # --------------------------------------------------------------------
        #
        # Range 1 sampai 3000 pixel untuk berbagai kamera/FOV.
        # --------------------------------------------------------------------

        tk.Label(
            self.root,
            text="Camera Focal Length (pixel)",
            font=("Arial", 11, "bold"),
        ).pack(padx=10, pady=(8, 0), anchor="w")

        self.width_scale = tk.Scale(
            self.root,
            from_=1,
            to=3000,
            resolution=1,
            orient=tk.HORIZONTAL,
            variable=self.width_var,
            length=450,
            showvalue=True,
        )

        self.width_scale.pack(padx=10, fill="x")

        # --------------------------------------------------------------------
        # INFO
        # --------------------------------------------------------------------

        self.info_label = tk.Label(
            self.root,
            text="D_m = (object_cm / 100) * focal_px / bbox_px",
            font=("Consolas", 10),
        )

        self.info_label.pack(padx=10, pady=(8, 0))

        # Menutup calibration panel TIDAK menghentikan video.
        #
        # Program akan mempertahankan nilai slider terakhir.
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def update(self):
        """
        Proses event Tkinter satu kali.

        Kita tidak menggunakan root.mainloop() karena main loop utama dimiliki
        oleh OpenCV/video inference.

        Sebagai gantinya setiap frame:
        
            calibration_ui.update()

        dipanggil untuk memproses event slider/window.
        """

        if self.root is None:
            return

        try:
            # Simpan nilai terbaru sebelum event loop berikutnya.
            self.object_width_cm = max(0.001, float(self.distance_var.get()))
            self.focal_length_px = max(1.0, float(self.width_var.get()))

            self.root.update_idletasks()
            self.root.update()

        except self.tk.TclError:
            # Window mungkin ditutup user.
            self.root = None

    def get_values(self) -> tuple[float, float]:
        """Ambil object width cm dan focal length px terbaru."""

        # Kalau window masih hidup, baca nilai terbaru terlebih dahulu.
        if self.root is not None:
            try:
                self.object_width_cm = max(
                    0.001,
                    float(self.distance_var.get()),
                )

                self.focal_length_px = max(
                    1.0,
                    float(self.width_var.get()),
                )

            except self.tk.TclError:
                pass

        return self.object_width_cm, self.focal_length_px

    def close(self):
        """Tutup hanya calibration panel, bukan video."""

        if self.root is None:
            return

        # Pertahankan nilai terakhir slider.
        try:
            self.object_width_cm = max(0.001, float(self.distance_var.get()))
            self.focal_length_px = max(1.0, float(self.width_var.get()))
        except self.tk.TclError:
            pass

        try:
            self.root.destroy()
        except self.tk.TclError:
            pass

        self.root = None


# ============================================================================
# CAMERA-TO-OBJECT PIXEL DISTANCE
# ============================================================================
#
# Rumus pinhole memakai LEBAR bbox float, bukan tinggi dan bukan koordinat yang
# sudah dibulatkan untuk OpenCV:
#
#       distance_m = (object_width_cm / 100) * focal_px / bbox_width_px
#
# Contoh parameter CLI:
#
#       --object-width-cm 35 --focal-length-px 200
#
# Jika lebar bbox hasil YOLO adalah 5 px:
#
#       distance = (35 / 100) * 200 / 5
#                = 14 meter
#
# Nama argumen lama tetap menjadi alias agar command lama tidak error:
#
#       --ref-distance    == --object-width-cm   (nilai dalam cm)
#       --ref-bbox-width  == --focal-length-px   (nilai dalam px)
#
# ============================================================================


def estimate_distance(
    bbox,
    object_width_cm: float,
    focal_length_px: float,
) -> float | None:
    """Compatibility wrapper untuk estimator pixel yang unitnya eksplisit."""

    return estimate_camera_distance_m(
        bbox,
        object_width_cm=object_width_cm,
        focal_length_px=focal_length_px,
    )


def apply_bbox_distances_to_pairs(
    pairs,
    detections,
    object_width_cm: float,
    focal_length_px: float,
):
    """Isi jarak object dan midpoint dengan pinhole pixel-distance.

    Pairing dan pemilihan target tetap memakai geometri dasar bbox/Y2. Fungsi
    ini HANYA mengisi nilai meter dari panjang object, focal length pixel, dan
    lebar bbox masing-masing buoy. Pairing/garis tidak diubah di sini.
    """

    for pair in pairs:
        green_distance = estimate_distance(
            detections[pair["green_index"]]["box"],
            object_width_cm,
            focal_length_px,
        )
        red_distance = estimate_distance(
            detections[pair["red_index"]]["box"],
            object_width_cm,
            focal_length_px,
        )
        midpoint_distance = average_valid_distances(
            green_distance,
            red_distance,
        )

        pair["green_distance_m"] = green_distance
        pair["red_distance_m"] = red_distance
        pair["distance_m"] = midpoint_distance
        pair["forward_distance_m"] = midpoint_distance
        pair["distance_source"] = "known_width_pixels"

    return pairs


# ============================================================================
# WEBSOCKET BUOY PAYLOAD
# ============================================================================
#
# Payload:
#
# {
#   "buoys":[
#     {
#       "class":"red_buoy",
#       "confidence":0.94,
#       "distance":2.31,
#       "x":-0.27,
#       "width":182
#     }
#   ]
# }
#
# Tidak ada timestamp.
#
# x:
#
#       -1 = kiri frame
#        0 = tengah frame
#       +1 = kanan frame
#
# Jika tidak ada buoy:
#
#       {"buoys":[]}
#
# Empty array tetap dikirim supaya autonomous system tahu bahwa target sudah
# hilang dan tidak terus memakai detection frame lama.
# ============================================================================


def build_buoy_payload(
    detections,
    frame_width: int,
    object_width_cm: float,
    focal_length_px: float,
    pairs=None,
    target_pair=None,
) -> dict:
    """Buat state buoy dan pasangan merah-hijau untuk WebSocket."""

    pairs = pairs or []
    buoys = []
    paired_ids = {}

    for pair in pairs:
        paired_ids[pair["green_index"]] = pair["id"]
        paired_ids[pair["red_index"]] = pair["id"]

    for detection_index, detection in enumerate(detections):
        x1, y1, x2, y2 = map(float, detection["box"])

        bbox_width = x2 - x1

        if bbox_width <= 0:
            continue

        center_x = (x1 + x2) * 0.5
        center_y = (y1 + y2) * 0.5

        # Ubah posisi horizontal pixel menjadi -1 sampai +1.
        horizontal_position = (center_x / (frame_width * 0.5)) - 1.0

        # Semua buoy kembali memakai rumus awal berbasis lebar bbox. Status
        # paired/unpaired tidak boleh mengubah sumber nilai meter.
        distance = estimate_distance(
            detection["box"],
            object_width_cm,
            focal_length_px,
        )
        distance_source = "known_width_pixels"

        buoys.append({
            "class": detection["class_name"],
            "confidence": round(float(detection["score"]), 4),
            "distance": round(distance, 3) if distance is not None else None,
            "distance_source": distance_source,
            "pair_id": paired_ids.get(detection_index),
            "x": round(horizontal_position, 4),
            "center_px": {
                "x": round(center_x, 2),
                "y": round(center_y, 2),
            },
            "width": round(bbox_width, 1),
        })

    pair_payload = []

    for pair in pairs:
        midpoint_x, midpoint_y = pair["midpoint"]
        pair_payload.append({
            "id": pair["id"],
            "is_target": pair is target_pair,
            "front_y": round(pair["front_y"], 2),
            "distance_source": pair["distance_source"],
            "green_detection_index": pair["green_index"],
            "red_detection_index": pair["red_index"],
            "known_width_m": round(pair["known_width_m"], 3),
            "pixel_distance": round(pair["pixel_distance"], 2),
            "horizontal_pixel_distance": round(
                pair["horizontal_pixel_distance"], 2
            ),
            "midpoint_px": {
                "x": round(midpoint_x, 2),
                "y": round(midpoint_y, 2),
            },
            "midpoint_x": round(
                (midpoint_x / (frame_width * 0.5)) - 1.0,
                4,
            ),
            "distance": (
                round(pair["distance_m"], 3)
                if pair["distance_m"] is not None
                else None
            ),
            "forward_distance": (
                round(pair["forward_distance_m"], 3)
                if pair["forward_distance_m"] is not None
                else None
            ),
            "bearing_degrees": round(pair["bearing_degrees"], 2),
        })

    return {
        "buoys": buoys,
        "pairs": pair_payload,
        "target_pair_id": target_pair["id"] if target_pair else None,
        "focus_side": FOCUS_SIDE,
    }


# ============================================================================
# DRAW DETECTIONS
# ============================================================================


def draw_detections_with_distance(
    frame,
    detections,
    object_width_cm: float,
    focal_length_px: float,
    pairs=None,
    target_pair=None,
):
    """Gambar bbox, jarak buoy, pasangan, midpoint, dan garis POV."""

    frame_height = frame.shape[0]
    pairs = pairs or []

    for detection_index, detection in enumerate(detections):
        x1, y1, x2, y2 = map(int, detection["box"])
        class_name = detection["class_name"]
        confidence = detection["score"]

        # Sama seperti versi awal: jarak setiap detection selalu dihitung dari
        # lebar bbox-nya sendiri, termasuk detection yang sudah berpasangan.
        distance = estimate_distance(
            detection["box"],
            object_width_cm,
            focal_length_px,
        )

        if distance is not None:
            label = f"{class_name} {confidence:.2f} | {distance:.2f} m"
        else:
            label = f"{class_name} {confidence:.2f}"

        color_name = buoy_color(detection)
        box_color = (
            (0, 0, 255) if color_name == "red"
            else (0, 255, 0) if color_name == "green"
            else (0, 255, 255)
        )

        # Bounding box mengikuti warna buoy; kelas lain dibuat kuning.
        cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)

        # Ukuran label.
        (text_width, text_height), baseline = cv2.getTextSize(
            label,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            2,
        )

        text_y = max(y1, text_height + baseline + 6)

        # Background label.
        cv2.rectangle(
            frame,
            (x1, text_y - text_height - baseline - 6),
            (x1 + text_width + 8, text_y + 2),
            box_color,
            -1,
        )

        # Class + confidence + distance.
        cv2.putText(
            frame,
            label,
            (x1 + 4, text_y - baseline - 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 0, 0),
            2,
            cv2.LINE_AA,
        )

        # Width pixel aktual ditampilkan untuk audit rumus jarak.
        bbox_width = x2 - x1

        cv2.putText(
            frame,
            f"w={bbox_width}px",
            (x1, min(frame_height - 10, y2 + 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            box_color,
            1,
            cv2.LINE_AA,
        )

    pov = (frame.shape[1] // 2, frame_height - 1)
    cv2.circle(frame, pov, 6, (255, 255, 255), -1, cv2.LINE_AA)
    cv2.putText(
        frame,
        "POV",
        (pov[0] + 9, max(18, pov[1] - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.50,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )

    for pair in pairs:
        green_point = tuple(round(value) for value in pair["green_center"])
        red_point = tuple(round(value) for value in pair["red_center"])
        midpoint = tuple(round(value) for value in pair["midpoint"])
        is_target = pair is target_pair

        # Garis cyan menunjukkan semua pasangan valid untuk debugging.
        # HANYA pair yang sudah dipilih satu kali di main loop boleh mendapat
        # garis POV magenta. Jangan memilih target ulang di fungsi drawing.
        cv2.line(frame, green_point, red_point, (255, 255, 0), 2, cv2.LINE_AA)
        if is_target:
            cv2.line(frame, pov, midpoint, (255, 0, 255), 3, cv2.LINE_AA)
        cv2.circle(frame, midpoint, 7, (255, 255, 0), -1, cv2.LINE_AA)
        cv2.drawMarker(
            frame,
            midpoint,
            (0, 0, 0),
            cv2.MARKER_CROSS,
            13,
            2,
            cv2.LINE_AA,
        )

        pair_label = (
            f"PAIR {pair['id']} | {pair['pixel_distance']:.2f}px"
            f" = {pair['known_width_m']:.2f}m"
        )
        if is_target:
            distance_label = (
                f"TARGET TERDEKAT {pair['distance_m']:.2f}m | "
                f"arah {pair['bearing_degrees']:+.1f}deg"
            )
        else:
            distance_label = f"KAPAL->MID {pair['distance_m']:.2f}m"
        label_x = max(5, min(midpoint[0] - 120, frame.shape[1] - 330))
        label_y = max(42, midpoint[1] - 18)

        cv2.putText(
            frame,
            pair_label,
            (label_x, label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            (255, 255, 0),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            distance_label,
            (label_x, label_y + 19),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (255, 0, 255) if is_target else (255, 255, 0),
            2,
            cv2.LINE_AA,
        )

    return frame


# ============================================================================
# MAIN
# ============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "YOLOv8 DirectML/CUDA/TensorRT + distance + pairing + WebSocket"
        )
    )

    # ------------------------------------------------------------------------
    # INPUT
    # ------------------------------------------------------------------------

    parser.add_argument("model", help="Path model YOLO .pt/.engine")
    parser.add_argument(
        "video",
        nargs="?",
        help="Path video atau camera ID, contoh 0. Opsional jika --gstreamer.",
    )
    parser.add_argument(
        "--gstreamer",
        help="Pipeline GStreamer untuk CSI camera Jetson (apit dengan quote)",
    )

    # ------------------------------------------------------------------------
    # YOLO
    # ------------------------------------------------------------------------

    parser.add_argument("--imgsz", type=int, default=640, help="YOLO input size")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    parser.add_argument("--iou", type=float, default=0.45, help="NMS IoU threshold")
    parser.add_argument("--cpu", action="store_true", help="Gunakan CPU")
    parser.add_argument(
        "--backend",
        choices=("auto", "directml", "cuda"),
        default="auto",
        help="auto: CUDA di Jetson ARM64, DirectML di platform lain",
    )
    parser.add_argument(
        "--force-export",
        action="store_true",
        help="DirectML: PT->ONNX; CUDA: PT->TensorRT FP16 di perangkat ini",
    )

    # ------------------------------------------------------------------------
    # VIDEO
    # ------------------------------------------------------------------------

    parser.add_argument(
        "--output",
        help="Output video. Default: output/<nama>_detected.mp4",
    )

    parser.add_argument("--no-save", action="store_true", help="Jangan simpan output")
    parser.add_argument("--no-show", action="store_true", help="Jangan tampilkan OpenCV preview")

    # ------------------------------------------------------------------------
    # PIXEL DISTANCE PARAMETERS
    # ------------------------------------------------------------------------

    parser.add_argument(
        "--object-width-cm",
        "--ref-distance",
        dest="object_width_cm",
        type=float,
        default=35.0,
        help=(
            "Lebar nyata object dalam centimeter. "
            "--ref-distance dipertahankan sebagai alias. Default: 35"
        ),
    )

    parser.add_argument(
        "--focal-length-px",
        "--ref-bbox-width",
        dest="focal_length_px",
        type=float,
        default=200.0,
        help=(
            "Focal length kamera dalam pixel. "
            "--ref-bbox-width dipertahankan sebagai alias. Default: 200"
        ),
    )

    # Jarak paired-buoy dihitung otomatis dari bentang aturan ASV 2 meter.
    # HFOV adalah spesifikasi tetap kamera, bukan kalibrasi jarak per lokasi.
    parser.add_argument(
        "--buoy-pair-width",
        type=float,
        default=2.0,
        help="Jarak nyata pusat buoy hijau-merah. Default: 2.0 meter",
    )

    parser.add_argument(
        "--pair-max-vertical-gap",
        type=float,
        default=0.20,
        help="Batas selisih Y pasangan terhadap tinggi frame. Default: 0.20",
    )

    # ------------------------------------------------------------------------
    # LIVE CALIBRATION UI
    # ------------------------------------------------------------------------
    #
    # Aktifkan:
    #
    #   --calibration-ui
    #
    # Kalau tidak digunakan, script berjalan persis seperti sebelumnya.
    # ------------------------------------------------------------------------

    parser.add_argument(
        "--calibration-ui",
        action="store_true",
        help="Slider live untuk object width cm dan focal length px",
    )

    # ------------------------------------------------------------------------
    # WEBSOCKET
    # ------------------------------------------------------------------------

    parser.add_argument(
        "--ws-url",
        default=None,
        help="Target WebSocket. Contoh: ws://192.168.1.50:8765",
    )

    args = parser.parse_args()

    if args.object_width_cm <= 0:
        raise ValueError("--object-width-cm harus > 0")

    if args.focal_length_px <= 0:
        raise ValueError("--focal-length-px harus > 0")

    if args.buoy_pair_width <= 0:
        raise ValueError("--buoy-pair-width harus > 0")

    if not 0 <= args.pair_max_vertical_gap <= 1:
        raise ValueError("--pair-max-vertical-gap harus di antara 0 dan 1")

    # ------------------------------------------------------------------------
    # VIDEO / CAMERA SOURCE
    # ------------------------------------------------------------------------

    # Validasi dan buka source sebelum memuat model yang relatif mahal.
    cap, source_label, output_stem = open_video_source(args.video, args.gstreamer)
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"Gagal membuka source: {source_label}")

    # ------------------------------------------------------------------------
    # YOLO ENGINE
    # ------------------------------------------------------------------------

    try:
        engine = create_inference_engine(args)
    except Exception:
        cap.release()
        raise

    # ------------------------------------------------------------------------
    # CALIBRATION UI
    # ------------------------------------------------------------------------

    calibration_ui = None

    if args.calibration_ui:
        calibration_ui = CalibrationUI(
            object_width_cm=args.object_width_cm,
            focal_length_px=args.focal_length_px,
        )

    # ------------------------------------------------------------------------
    # WEBSOCKET
    # ------------------------------------------------------------------------

    ws_sender = None

    if args.ws_url:
        ws_sender = LowLatencyWebSocketSender(args.ws_url)

    # ------------------------------------------------------------------------
    # VIDEO SOURCE METADATA
    # ------------------------------------------------------------------------

    # Ambil satu frame nyata; property width/height beberapa backend kamera
    # bernilai nol sampai frame pertama diterima.
    first_frame_ok, pending_frame = cap.read()
    if not first_frame_ok or pending_frame is None:
        cap.release()
        if calibration_ui:
            calibration_ui.close()
        if ws_sender:
            ws_sender.close()
        raise RuntimeError(f"Source terbuka tetapi frame tidak dapat dibaca: {source_label}")

    height, width = pending_frame.shape[:2]
    source_fps = float(cap.get(cv2.CAP_PROP_FPS))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if source_fps <= 0 or source_fps != source_fps:
        source_fps = 30.0

    # ------------------------------------------------------------------------
    # OUTPUT
    # ------------------------------------------------------------------------

    output_path = (
        Path(args.output)
        if args.output
        else Path("output") / f"{output_stem}_detected.mp4"
    )

    writer = None

    if not args.no_save:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        writer = cv2.VideoWriter(
            str(output_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            source_fps,
            (width, height),
        )

        if not writer.isOpened():
            cap.release()

            if calibration_ui:
                calibration_ui.close()

            if ws_sender:
                ws_sender.close()

            raise RuntimeError(f"Gagal membuat video output: {output_path}")

    # ------------------------------------------------------------------------
    # INFORMATION
    # ------------------------------------------------------------------------

    print()
    print("=" * 60)
    print("VIDEO INFORMATION")
    print("=" * 60)
    print(f"Input          : {source_label}")
    print(f"Backend        : {selected_backend(args.backend)}")
    print(f"Resolution     : {width}x{height}")
    print(f"FPS source     : {source_fps:.3f}")
    print(f"Calibration UI : {'enabled' if calibration_ui else 'disabled'}")

    if total_frames > 0:
        print(f"Frames         : {total_frames}")
        print(f"Duration       : {total_frames / source_fps:.2f} sec")
    else:
        print("Frames         : unknown")

    if writer:
        print(f"Output         : {output_path}")

    print()
    print("=" * 60)
    print("CAMERA-TO-OBJECT PIXEL DISTANCE")
    print("=" * 60)
    print(f"Known object width   : {args.object_width_cm:.2f} cm")
    print(f"Camera focal length  : {args.focal_length_px:.2f} px")
    print("Formula              : D = (width_cm/100) * focal_px / bbox_px")
    print(f"Pair span metadata   : {args.buoy_pair_width:.2f} m")

    print()
    print("=" * 60)
    print("WEBSOCKET")
    print("=" * 60)
    print(f"Target : {args.ws_url if args.ws_url else 'disabled'}")
    print("=" * 60)

    if not args.no_show:
        print("\nTekan Q atau ESC untuk berhenti.")

    frame_index = 0
    processing_fps_ema = 0.0
    started = time.perf_counter()

    # =========================================================================
    # MAIN VIDEO LOOP
    # =========================================================================

    try:
        while True:
            loop_start = time.perf_counter()

            # ----------------------------------------------------------------
            # UPDATE TKINTER
            # ----------------------------------------------------------------
            #
            # Slider diproses sebelum inference frame berikutnya.
            #
            # Tidak menggunakan Tkinter mainloop(), karena loop utama dimiliki
            # oleh video processor.
            # ----------------------------------------------------------------

            if calibration_ui:
                calibration_ui.update()

                object_width_cm, focal_length_px = (
                    calibration_ui.get_values()
                )
            else:
                object_width_cm = args.object_width_cm
                focal_length_px = args.focal_length_px

            # ----------------------------------------------------------------
            # READ VIDEO FRAME
            # ----------------------------------------------------------------

            camera_started = time.perf_counter()

            if pending_frame is not None:
                success, frame = True, pending_frame
                pending_frame = None
            else:
                success, frame = cap.read()

            camera_ms = (time.perf_counter() - camera_started) * 1000.0

            if not success:
                break

            frame_index += 1

            # ----------------------------------------------------------------
            # YOLO INFERENCE
            # ----------------------------------------------------------------

            predict_started = time.perf_counter()
            detections, inference_ms = engine.predict(frame)
            predict_ms = (time.perf_counter() - predict_started) * 1000.0
            post_started = time.perf_counter()

            # ---------------------------------------------------------------
            # PAIR BUOY HIJAU-MERAH
            # ---------------------------------------------------------------
            # Semua koordinat tetap float sehingga jarak pixel dan midpoint
            # dapat memiliki angka desimal. Pembulatan hanya saat menggambar.

            pairs = pair_buoys(
                detections,
                frame_width=width,
                frame_height=height,
                known_pair_width_m=args.buoy_pair_width,
                max_vertical_gap_ratio=args.pair_max_vertical_gap,
                focus_side=FOCUS_SIDE,
            )

            # Jarak meter dikembalikan ke metode awal. Pairing 2 meter hanya
            # menyediakan struktur gerbang, pixel distance, dan midpoint.
            # Nilai object/focal terbaru dari slider diterapkan pada frame ini.
            apply_bbox_distances_to_pairs(
                pairs,
                detections,
                object_width_cm,
                focal_length_px,
            )

            # SATU sumber kebenaran target untuk frame ini:
            #
            # 1. pair_buoys sudah membuang orientasi pasangan yang salah;
            # 2. frontmost_pair memilih front_y terbesar di SELURUH frame;
            # 3. object dict yang sama diteruskan ke payload DAN drawing.
            #
            # Dilarang memilih ulang berdasarkan sisi/tengah frame di bawah.
            target_pair = frontmost_pair(pairs)

            # ----------------------------------------------------------------
            # WEBSOCKET
            # ----------------------------------------------------------------
            #
            # Perhatikan:
            #
            # object_width_cm dan focal_length_px di sini merupakan
            # nilai slider TERBARU.
            #
            # Jadi perubahan slider langsung mempengaruhi WebSocket.
            # ----------------------------------------------------------------

            if ws_sender:
                ws_sender.send(
                    build_buoy_payload(
                        detections,
                        frame_width=width,
                        object_width_cm=object_width_cm,
                        focal_length_px=focal_length_px,
                        pairs=pairs,
                        target_pair=target_pair,
                    )
                )

            # ----------------------------------------------------------------
            # DRAW
            # ----------------------------------------------------------------

            draw_detections_with_distance(
                frame,
                detections,
                object_width_cm=object_width_cm,
                focal_length_px=focal_length_px,
                pairs=pairs,
                target_pair=target_pair,
            )

            post_ms = (time.perf_counter() - post_started) * 1000.0

            # ----------------------------------------------------------------
            # FPS
            # ----------------------------------------------------------------

            elapsed = max(time.perf_counter() - loop_start, 1e-9)
            fps_now = 1.0 / elapsed

            if processing_fps_ema == 0.0:
                processing_fps_ema = fps_now
            else:
                processing_fps_ema = 0.9 * processing_fps_ema + 0.1 * fps_now

            # ----------------------------------------------------------------
            # PERFORMANCE + LIVE CALIBRATION OVERLAY
            # ----------------------------------------------------------------
            #
            # Current calibration juga ditampilkan di video.
            #
            # Jadi saat menggeser Tkinter:
            #
            #   REF 2.00m / 180px
            #
            # langsung berubah.
            # ----------------------------------------------------------------

            overlay = (
                f"PROC {processing_fps_ema:.1f} FPS | "
                f"INFER {inference_ms:.1f} ms | "
                f"objects {len(detections)}"
            )

            calibration_overlay = (
                f"OBJECT {object_width_cm:.1f}cm | FOCAL {focal_length_px:.0f}px | "
                f"GREEN-{FOCUS_SIDE.upper()} | "
                f"target {target_pair['id'] if target_pair else '-'}"
            )

            cv2.putText(
                frame,
                overlay,
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

            cv2.putText(
                frame,
                calibration_overlay,
                (12, 56),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.60,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

            # ----------------------------------------------------------------
            # SAVE
            # ----------------------------------------------------------------

            if writer:
                writer.write(frame)

            # ----------------------------------------------------------------
            # PREVIEW
            # ----------------------------------------------------------------

            if not args.no_show:
                cv2.imshow(
                    "YOLOv8 - Pixel Distance + Buoy Pairing",
                    frame,
                )

                key = cv2.waitKey(1) & 0xFF

                if key in (ord("q"), 27):
                    print("\n[STOP] Dihentikan user.")
                    break

            # ----------------------------------------------------------------
            # TERMINAL PROGRESS
            # ----------------------------------------------------------------

            if total_frames > 0:
                progress = frame_index * 100.0 / total_frames
                progress_text = f"{progress:6.2f}% ({frame_index}/{total_frames})"
            else:
                progress_text = f"frame {frame_index}"

            print(
                f"\r[RUN] {progress_text} | "
                f"TRT {inference_ms:6.2f} ms | "
                f"YOLO {predict_ms:6.2f} ms | "
                f"CAM {camera_ms:6.2f} ms | "
                f"POST {post_ms:6.2f} ms | "
                f"{processing_fps_ema:6.2f} FPS | "
                f"{len(detections):3d} objects | "
                f"{len(pairs):2d} pairs",
                end="",
                flush=True,
            )

    finally:
        cap.release()

        if writer:
            writer.release()

        if ws_sender:
            ws_sender.close()

        if calibration_ui:
            calibration_ui.close()

        cv2.destroyAllWindows()

    # ------------------------------------------------------------------------
    # FINAL STATISTICS
    # ------------------------------------------------------------------------

    total_time = time.perf_counter() - started
    average_fps = frame_index / total_time if total_time > 0 else 0.0

    print()
    print()
    print("=" * 60)
    print("FINISHED")
    print("=" * 60)
    print(f"Frames processed : {frame_index}")
    print(f"Total time       : {total_time:.2f} s")
    print(f"Average          : {average_fps:.2f} FPS")

    return 0


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    try:
        raise SystemExit(main())

    except KeyboardInterrupt:
        print("\n[STOP] Dihentikan user.")
        raise SystemExit(130)

    except Exception as exc:
        print(f"\n[ERROR] {exc}", file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(1)
