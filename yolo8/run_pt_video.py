from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
from pathlib import Path

import cv2

from run_pt import YOLODirectML


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
#   Reference Distance
#       jarak fisik objek saat kalibrasi
#
#   Reference BBox Width
#       lebar bounding box YOLO pada jarak tersebut
#
# Nilai slider dibaca LANGSUNG setiap frame.
#
# Jadi user dapat menggeser slider ketika video sedang berjalan:
#
#       slider berubah
#           |
#           v
#       nilai kalibrasi berubah
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
    """Panel slider untuk melakukan kalibrasi distance secara live."""

    def __init__(
        self,
        reference_distance: float,
        reference_bbox_width: float,
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
        self.reference_distance = reference_distance
        self.reference_bbox_width = reference_bbox_width
        self.root = tk.Tk()

        self.root.title("YOLO Distance Calibration")
        self.root.geometry("480x260")
        self.root.resizable(True, False)

        # --------------------------------------------------------------------
        # VARIABLE TKINTER
        # --------------------------------------------------------------------

        self.distance_var = tk.DoubleVar(value=reference_distance)
        self.width_var = tk.DoubleVar(value=reference_bbox_width)

        # --------------------------------------------------------------------
        # REFERENCE DISTANCE
        # --------------------------------------------------------------------
        #
        # Range dibuat 0.1 sampai 20 meter.
        #
        # Kalau arena lebih besar bisa dinaikkan.
        # --------------------------------------------------------------------

        tk.Label(
            self.root,
            text="Reference Distance (meter)",
            font=("Arial", 11, "bold"),
        ).pack(padx=10, pady=(12, 0), anchor="w")

        self.distance_scale = tk.Scale(
            self.root,
            from_=0.1,
            to=20.0,
            resolution=0.05,
            orient=tk.HORIZONTAL,
            variable=self.distance_var,
            length=450,
            showvalue=True,
        )

        self.distance_scale.pack(padx=10, fill="x")

        # --------------------------------------------------------------------
        # REFERENCE BBOX WIDTH
        # --------------------------------------------------------------------
        #
        # Range 1 sampai 1500 pixel.
        #
        # Cukup untuk video 640p, 720p, 1080p, dan sebagian besar input umum.
        # --------------------------------------------------------------------

        tk.Label(
            self.root,
            text="Reference Bounding Box Width (pixel)",
            font=("Arial", 11, "bold"),
        ).pack(padx=10, pady=(8, 0), anchor="w")

        self.width_scale = tk.Scale(
            self.root,
            from_=1,
            to=1500,
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
            text="D = D_ref * W_ref / W_current",
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
            self.reference_distance = max(0.001, float(self.distance_var.get()))
            self.reference_bbox_width = max(1.0, float(self.width_var.get()))

            self.root.update_idletasks()
            self.root.update()

        except self.tk.TclError:
            # Window mungkin ditutup user.
            self.root = None

    def get_values(self) -> tuple[float, float]:
        """Ambil nilai kalibrasi terbaru."""

        # Kalau window masih hidup, baca nilai terbaru terlebih dahulu.
        if self.root is not None:
            try:
                self.reference_distance = max(
                    0.001,
                    float(self.distance_var.get()),
                )

                self.reference_bbox_width = max(
                    1.0,
                    float(self.width_var.get()),
                )

            except self.tk.TclError:
                pass

        return self.reference_distance, self.reference_bbox_width

    def close(self):
        """Tutup hanya calibration panel, bukan video."""

        if self.root is None:
            return

        # Pertahankan nilai terakhir slider.
        try:
            self.reference_distance = max(0.001, float(self.distance_var.get()))
            self.reference_bbox_width = max(1.0, float(self.width_var.get()))
        except self.tk.TclError:
            pass

        try:
            self.root.destroy()
        except self.tk.TclError:
            pass

        self.root = None


# ============================================================================
# DISTANCE ESTIMATION
# ============================================================================
#
# Estimasi jarak menggunakan LEBAR bounding box.
#
# BUKAN tinggi.
#
# Rumus:
#
#       D = D_ref * W_ref / W_current
#
# D:
#       jarak objek sekarang
#
# D_ref:
#       jarak objek ketika dilakukan kalibrasi
#
# W_ref:
#       lebar bbox ketika kalibrasi
#
# W_current:
#       lebar bbox detection sekarang
#
# Contoh:
#
#       D_ref = 2 meter
#       W_ref = 200 pixel
#
# Kalau sekarang:
#
#       W_current = 100 pixel
#
# Maka:
#
#       D = 2 * 200 / 100
#         = 4 meter
#
# ============================================================================


def estimate_distance(
    bbox,
    reference_distance: float,
    reference_bbox_width: float,
) -> float | None:
    """Hitung estimasi jarak berdasarkan WIDTH bounding box."""

    x1, _, x2, _ = bbox
    bbox_width = float(x2 - x1)

    if bbox_width <= 0:
        return None

    return reference_distance * reference_bbox_width / bbox_width


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
    reference_distance: float,
    reference_bbox_width: float,
) -> dict:
    """Buat state buoy untuk dikirim melalui WebSocket."""

    buoys = []

    for detection in detections:
        x1, _, x2, _ = map(float, detection["box"])

        bbox_width = x2 - x1

        if bbox_width <= 0:
            continue

        center_x = (x1 + x2) * 0.5

        # Ubah posisi horizontal pixel menjadi -1 sampai +1.
        horizontal_position = (center_x / (frame_width * 0.5)) - 1.0

        distance = estimate_distance(
            detection["box"],
            reference_distance,
            reference_bbox_width,
        )

        buoys.append({
            "class": detection["class_name"],
            "confidence": round(float(detection["score"]), 4),
            "distance": round(distance, 3) if distance is not None else None,
            "x": round(horizontal_position, 4),
            "width": round(bbox_width, 1),
        })

    return {"buoys": buoys}


# ============================================================================
# DRAW DETECTIONS
# ============================================================================


def draw_detections_with_distance(
    frame,
    detections,
    reference_distance: float,
    reference_bbox_width: float,
):
    """Gambar bbox + confidence + WIDTH-based distance + bbox width."""

    frame_height = frame.shape[0]

    for detection in detections:
        x1, y1, x2, y2 = map(int, detection["box"])
        class_name = detection["class_name"]
        confidence = detection["score"]

        distance = estimate_distance(
            detection["box"],
            reference_distance,
            reference_bbox_width,
        )

        if distance is not None:
            label = f"{class_name} {confidence:.2f} | {distance:.2f} m"
        else:
            label = f"{class_name} {confidence:.2f}"

        # Bounding box.
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

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
            (0, 255, 0),
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

        # Width aktual ditampilkan untuk membantu mencari nilai W_ref.
        bbox_width = x2 - x1

        cv2.putText(
            frame,
            f"w={bbox_width}px",
            (x1, min(frame_height - 10, y2 + 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 255, 0),
            1,
            cv2.LINE_AA,
        )

    return frame


# ============================================================================
# MAIN
# ============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="YOLOv8 VIDEO FILE + width distance + calibration UI + WebSocket"
    )

    # ------------------------------------------------------------------------
    # INPUT
    # ------------------------------------------------------------------------

    parser.add_argument("model", help="Path model YOLO .pt")
    parser.add_argument("video", help="Path VIDEO FILE input")

    # ------------------------------------------------------------------------
    # YOLO
    # ------------------------------------------------------------------------

    parser.add_argument("--imgsz", type=int, default=640, help="YOLO input size")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    parser.add_argument("--iou", type=float, default=0.45, help="NMS IoU threshold")
    parser.add_argument("--cpu", action="store_true", help="Gunakan CPU")
    parser.add_argument("--force-export", action="store_true", help="Export ulang PT -> ONNX")

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
    # DISTANCE CALIBRATION
    # ------------------------------------------------------------------------

    parser.add_argument(
        "--ref-distance",
        type=float,
        default=2.0,
        help="Reference distance dalam meter. Default: 2.0",
    )

    parser.add_argument(
        "--ref-bbox-width",
        type=float,
        default=200.0,
        help="Reference bbox WIDTH dalam pixel. Default: 200",
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
        help="Tampilkan slider Tkinter untuk kalibrasi distance secara live",
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

    if args.ref_distance <= 0:
        raise ValueError("--ref-distance harus > 0")

    if args.ref_bbox_width <= 0:
        raise ValueError("--ref-bbox-width harus > 0")

    # ------------------------------------------------------------------------
    # VIDEO FILE ONLY
    # ------------------------------------------------------------------------

    video_path = Path(args.video)

    if not video_path.is_file():
        raise FileNotFoundError(f"Video tidak ditemukan: {video_path}")

    # ------------------------------------------------------------------------
    # YOLO ENGINE
    # ------------------------------------------------------------------------

    engine = YOLODirectML(
        args.model,
        imgsz=args.imgsz,
        conf=args.conf,
        iou=args.iou,
        cpu=args.cpu,
        force_export=args.force_export,
    )

    # ------------------------------------------------------------------------
    # CALIBRATION UI
    # ------------------------------------------------------------------------

    calibration_ui = None

    if args.calibration_ui:
        calibration_ui = CalibrationUI(
            reference_distance=args.ref_distance,
            reference_bbox_width=args.ref_bbox_width,
        )

    # ------------------------------------------------------------------------
    # WEBSOCKET
    # ------------------------------------------------------------------------

    ws_sender = None

    if args.ws_url:
        ws_sender = LowLatencyWebSocketSender(args.ws_url)

    # ------------------------------------------------------------------------
    # OPEN VIDEO FILE
    # ------------------------------------------------------------------------

    cap = cv2.VideoCapture(0)


    # cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        if calibration_ui:
            calibration_ui.close()

        if ws_sender:
            ws_sender.close()

        raise RuntimeError(f"Gagal membuka video: {video_path}")

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
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
        else Path("output") / f"{video_path.stem}_detected.mp4"
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
    print(f"Input          : {video_path}")
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
    print("DISTANCE CALIBRATION")
    print("=" * 60)
    print(f"Reference distance   : {args.ref_distance:.2f} m")
    print(f"Reference bbox width : {args.ref_bbox_width:.2f} px")
    print("Formula              : D = D_ref * W_ref / W")

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

                reference_distance, reference_bbox_width = (
                    calibration_ui.get_values()
                )
            else:
                reference_distance = args.ref_distance
                reference_bbox_width = args.ref_bbox_width

            # ----------------------------------------------------------------
            # READ VIDEO FRAME
            # ----------------------------------------------------------------

            success, frame = cap.read()

            if not success:
                break

            frame_index += 1

            # ----------------------------------------------------------------
            # YOLO INFERENCE
            # ----------------------------------------------------------------

            detections, inference_ms = engine.predict(frame)

            # ----------------------------------------------------------------
            # WEBSOCKET
            # ----------------------------------------------------------------
            #
            # Perhatikan:
            #
            # reference_distance dan reference_bbox_width di sini merupakan
            # nilai slider TERBARU.
            #
            # Jadi perubahan slider langsung mempengaruhi WebSocket.
            # ----------------------------------------------------------------

            if ws_sender:
                ws_sender.send(
                    build_buoy_payload(
                        detections,
                        frame_width=width,
                        reference_distance=reference_distance,
                        reference_bbox_width=reference_bbox_width,
                    )
                )

            # ----------------------------------------------------------------
            # DRAW
            # ----------------------------------------------------------------

            draw_detections_with_distance(
                frame,
                detections,
                reference_distance=reference_distance,
                reference_bbox_width=reference_bbox_width,
            )

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
                f"DML {inference_ms:.1f} ms | "
                f"objects {len(detections)}"
            )

            calibration_overlay = (
                f"REF {reference_distance:.2f}m | "
                f"W_REF {reference_bbox_width:.0f}px"
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
                    "YOLOv8 Video - Width Distance Calibration",
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
                f"{inference_ms:7.2f} ms | "
                f"{processing_fps_ema:6.2f} FPS | "
                f"{len(detections):3d} objects | "
                f"REF {reference_distance:.2f}m/{reference_bbox_width:.0f}px",
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
        raise SystemExit(1)