from __future__ import annotations

import argparse
import ast
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from ultralytics import YOLO


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
}


def ensure_onnx(
    pt_path: Path,
    imgsz: int,
    force: bool = False,
) -> Path:
    pt_path = pt_path.resolve()
    onnx_path = pt_path.with_suffix(".onnx")

    needs_export = (
        force
        or not onnx_path.exists()
        or pt_path.stat().st_mtime > onnx_path.stat().st_mtime
    )

    if not needs_export:
        print(f"[MODEL] ONNX up-to-date: {onnx_path}")
        return onnx_path

    print(
        f"[MODEL] Exporting {pt_path.name} "
        f"-> ONNX ({imgsz}x{imgsz})"
    )

    model = YOLO(str(pt_path))

    if model.task != "detect":
        raise RuntimeError(
            "Script ini khusus YOLO detection.\n"
            f"Model task terdeteksi: {model.task!r}"
        )

    exported = Path(
        model.export(
            format="onnx",
            imgsz=imgsz,
            dynamic=False,
            simplify=True,
            nms=False,
        )
    ).resolve()

    if not exported.exists():
        raise RuntimeError(
            "Ultralytics melaporkan export selesai, "
            f"tetapi file tidak ada:\n{exported}"
        )

    print(f"[MODEL] Export selesai: {exported}")

    return exported


def parse_names(
    session: ort.InferenceSession,
) -> dict[int, str]:

    metadata = session.get_modelmeta().custom_metadata_map
    raw = metadata.get("names")

    if not raw:
        return {}

    try:
        value = ast.literal_eval(raw)

    except (ValueError, SyntaxError):
        return {}

    if isinstance(value, dict):

        result: dict[int, str] = {}

        for key, name in value.items():

            try:
                result[int(key)] = str(name)

            except (TypeError, ValueError):
                continue

        return result

    if isinstance(value, (list, tuple)):

        return {
            index: str(name)
            for index, name in enumerate(value)
        }

    return {}


def letterbox(
    image: np.ndarray,
    size: tuple[int, int],
):

    target_h, target_w = size

    h, w = image.shape[:2]

    scale = min(
        target_w / w,
        target_h / h,
    )

    new_w = int(round(w * scale))
    new_h = int(round(h * scale))

    resized = cv2.resize(
        image,
        (new_w, new_h),
        interpolation=cv2.INTER_LINEAR,
    )

    canvas = np.full(
        (target_h, target_w, 3),
        114,
        dtype=np.uint8,
    )

    pad_x = (target_w - new_w) // 2
    pad_y = (target_h - new_h) // 2

    canvas[
        pad_y:pad_y + new_h,
        pad_x:pad_x + new_w
    ] = resized

    return (
        canvas,
        scale,
        pad_x,
        pad_y,
    )


def class_aware_nms(
    boxes: np.ndarray,
    scores: np.ndarray,
    class_ids: np.ndarray,
    iou_threshold: float,
) -> list[int]:

    keep: list[int] = []

    for class_id in np.unique(class_ids):

        indexes = np.where(
            class_ids == class_id
        )[0]

        order = indexes[
            np.argsort(
                scores[indexes]
            )[::-1]
        ]

        while order.size > 0:

            current = int(order[0])

            keep.append(current)

            if order.size == 1:
                break

            rest = order[1:]

            xx1 = np.maximum(
                boxes[current, 0],
                boxes[rest, 0],
            )

            yy1 = np.maximum(
                boxes[current, 1],
                boxes[rest, 1],
            )

            xx2 = np.minimum(
                boxes[current, 2],
                boxes[rest, 2],
            )

            yy2 = np.minimum(
                boxes[current, 3],
                boxes[rest, 3],
            )

            inter_w = np.maximum(
                0.0,
                xx2 - xx1,
            )

            inter_h = np.maximum(
                0.0,
                yy2 - yy1,
            )

            intersection = (
                inter_w * inter_h
            )

            area_current = (
                np.maximum(
                    0.0,
                    boxes[current, 2]
                    - boxes[current, 0],
                )
                *
                np.maximum(
                    0.0,
                    boxes[current, 3]
                    - boxes[current, 1],
                )
            )

            area_rest = (
                np.maximum(
                    0.0,
                    boxes[rest, 2]
                    - boxes[rest, 0],
                )
                *
                np.maximum(
                    0.0,
                    boxes[rest, 3]
                    - boxes[rest, 1],
                )
            )

            union = (
                area_current
                + area_rest
                - intersection
            )

            iou = (
                intersection
                /
                np.maximum(
                    union,
                    1e-7,
                )
            )

            order = rest[
                iou <= iou_threshold
            ]

    return keep


class YOLODirectML:

    def __init__(
        self,
        model_path: str | Path,
        imgsz: int = 640,
        conf: float = 0.25,
        iou: float = 0.45,
        cpu: bool = False,
        force_export: bool = False,
    ):

        self.pt_path = Path(
            model_path
        )

        if not self.pt_path.is_file():

            raise FileNotFoundError(
                f"Model tidak ditemukan: "
                f"{self.pt_path}"
            )

        self.conf = conf
        self.iou = iou

        self.onnx_path = ensure_onnx(
            self.pt_path,
            imgsz,
            force_export,
        )

        available = (
            ort.get_available_providers()
        )

        print(
            "[ORT] Available providers:",
            available,
        )

        if cpu:

            providers = [
                "CPUExecutionProvider",
            ]

        else:

            if (
                "DmlExecutionProvider"
                not in available
            ):

                raise RuntimeError(
                    "\n"
                    "DmlExecutionProvider "
                    "tidak tersedia.\n"
                    "\n"
                    f"Provider tersedia: "
                    f"{available}\n"
                    "\n"
                    "Pastikan package ini "
                    "terinstall:\n"
                    "\n"
                    "pip install "
                    "onnxruntime-directml\n"
                    "\n"
                    "Gunakan --cpu kalau "
                    "memang ingin CPU."
                )

            providers = [
                "DmlExecutionProvider",
                "CPUExecutionProvider",
            ]

        options = ort.SessionOptions()

        options.graph_optimization_level = (
            ort.GraphOptimizationLevel
            .ORT_ENABLE_ALL
        )

        # Requirement DirectML.
        options.enable_mem_pattern = False

        options.execution_mode = (
            ort.ExecutionMode
            .ORT_SEQUENTIAL
        )

        print(
            "[ORT] Creating session..."
        )

        self.session = (
            ort.InferenceSession(
                str(self.onnx_path),
                sess_options=options,
                providers=providers,
            )
        )

        self.input = (
            self.session
            .get_inputs()[0]
        )

        shape = self.input.shape

        if (
            len(shape) != 4
            or not isinstance(
                shape[2],
                int,
            )
            or not isinstance(
                shape[3],
                int,
            )
        ):

            raise RuntimeError(
                "Model ONNX harus "
                "static NCHW [1,3,H,W].\n"
                f"Input shape sekarang: "
                f"{shape}\n"
                "\n"
                "Hapus file .onnx "
                "lalu jalankan kembali."
            )

        self.input_h = int(
            shape[2]
        )

        self.input_w = int(
            shape[3]
        )

        self.names = parse_names(
            self.session
        )

        print()
        print(
            f"[ORT] Version   : "
            f"{ort.__version__}"
        )

        print(
            f"[ORT] Providers : "
            f"{self.session.get_providers()}"
        )

        print(
            f"[ORT] Input     : "
            f"{self.input.name} "
            f"{shape}"
        )

        print(
            f"[ORT] Classes   : "
            f"{len(self.names)}"
        )

        print()
        print(
            "[ORT] Warm-up..."
        )

        dummy = np.zeros(
            (
                1,
                3,
                self.input_h,
                self.input_w,
            ),
            dtype=np.float32,
        )

        self.session.run(
            None,
            {
                self.input.name:
                dummy
            },
        )

        print(
            "[ORT] Ready."
        )

    def preprocess(
        self,
        frame: np.ndarray,
    ):

        (
            image,
            scale,
            pad_x,
            pad_y,
        ) = letterbox(
            frame,
            (
                self.input_h,
                self.input_w,
            ),
        )

        image = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2RGB,
        )

        image = (
            image.astype(
                np.float32
            )
            / 255.0
        )

        image = np.transpose(
            image,
            (2, 0, 1),
        )

        image = image[None]

        image = np.ascontiguousarray(
            image
        )

        return (
            image,
            scale,
            pad_x,
            pad_y,
        )

    def postprocess(
        self,
        raw_output: np.ndarray,
        original_shape:
            tuple[int, int],
        scale: float,
        pad_x: int,
        pad_y: int,
    ) -> list[dict]:

        pred = np.asarray(
            raw_output
        )

        if pred.ndim == 3:
            pred = pred[0]

        if pred.ndim != 2:

            raise RuntimeError(
                "Output ONNX "
                "tidak dikenali: "
                f"{pred.shape}"
            )

        expected_attrs = (
            4 + len(self.names)
            if self.names
            else None
        )

        if (
            expected_attrs
            and pred.shape[0]
            == expected_attrs
        ):

            pred = pred.T

        elif (
            expected_attrs
            and pred.shape[1]
            == expected_attrs
        ):

            pass

        elif (
            pred.shape[0]
            < pred.shape[1]
        ):

            pred = pred.T

        if pred.shape[1] <= 4:

            raise RuntimeError(
                "Output detection "
                "tidak valid: "
                f"{pred.shape}"
            )

        boxes_xywh = (
            pred[:, :4]
        )

        class_scores = (
            pred[:, 4:]
        )

        class_ids = np.argmax(
            class_scores,
            axis=1,
        )

        scores = class_scores[
            np.arange(
                class_scores.shape[0]
            ),
            class_ids,
        ]

        mask = (
            scores >= self.conf
        )

        boxes_xywh = (
            boxes_xywh[mask]
        )

        scores = (
            scores[mask]
            .astype(np.float32)
        )

        class_ids = (
            class_ids[mask]
            .astype(np.int32)
        )

        if boxes_xywh.size == 0:
            return []

        boxes = np.empty_like(
            boxes_xywh,
            dtype=np.float32,
        )

        boxes[:, 0] = (
            boxes_xywh[:, 0]
            - boxes_xywh[:, 2]
            / 2.0
        )

        boxes[:, 1] = (
            boxes_xywh[:, 1]
            - boxes_xywh[:, 3]
            / 2.0
        )

        boxes[:, 2] = (
            boxes_xywh[:, 0]
            + boxes_xywh[:, 2]
            / 2.0
        )

        boxes[:, 3] = (
            boxes_xywh[:, 1]
            + boxes_xywh[:, 3]
            / 2.0
        )

        boxes[:, [0, 2]] -= (
            pad_x
        )

        boxes[:, [1, 3]] -= (
            pad_y
        )

        boxes /= scale

        (
            original_h,
            original_w,
        ) = original_shape

        boxes[:, [0, 2]] = (
            np.clip(
                boxes[:, [0, 2]],
                0,
                original_w - 1,
            )
        )

        boxes[:, [1, 3]] = (
            np.clip(
                boxes[:, [1, 3]],
                0,
                original_h - 1,
            )
        )

        keep = class_aware_nms(
            boxes,
            scores,
            class_ids,
            self.iou,
        )

        detections = []

        for index in keep:

            class_id = int(
                class_ids[index]
            )

            detections.append(
                {
                    "box":
                        boxes[index],

                    "score":
                        float(
                            scores[index]
                        ),

                    "class_id":
                        class_id,

                    "class_name":
                        self.names.get(
                            class_id,
                            str(class_id),
                        ),
                }
            )

        return detections

    def predict(
        self,
        frame: np.ndarray,
    ):

        (
            tensor,
            scale,
            pad_x,
            pad_y,
        ) = self.preprocess(
            frame
        )

        start = (
            time.perf_counter()
        )

        outputs = self.session.run(
            None,
            {
                self.input.name:
                tensor
            },
        )

        inference_ms = (
            (
                time.perf_counter()
                - start
            )
            * 1000.0
        )

        detections = (
            self.postprocess(
                outputs[0],
                frame.shape[:2],
                scale,
                pad_x,
                pad_y,
            )
        )

        return (
            detections,
            inference_ms,
        )


def draw_detections(
    frame: np.ndarray,
    detections: list[dict],
) -> np.ndarray:

    for detection in detections:

        (
            x1,
            y1,
            x2,
            y2,
        ) = map(
            int,
            detection["box"],
        )

        label = (
            f'{detection["class_name"]} '
            f'{detection["score"]:.2f}'
        )

        cv2.rectangle(
            frame,
            (x1, y1),
            (x2, y2),
            (0, 255, 0),
            2,
        )

        (
            (text_width, text_height),
            baseline,
        ) = cv2.getTextSize(
            label,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            2,
        )

        text_y = max(
            text_height
            + baseline
            + 4,
            y1,
        )

        cv2.rectangle(
            frame,
            (
                x1,
                text_y
                - text_height
                - baseline
                - 6,
            ),
            (
                x1
                + text_width
                + 6,
                text_y + 2,
            ),
            (0, 255, 0),
            -1,
        )

        cv2.putText(
            frame,
            label,
            (
                x1 + 3,
                text_y
                - baseline
                - 2,
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 0, 0),
            2,
            cv2.LINE_AA,
        )

    return frame


def run_image(
    engine: YOLODirectML,
    source: Path,
    output: Path | None,
    show: bool,
):

    frame = cv2.imread(
        str(source)
    )

    if frame is None:

        raise RuntimeError(
            "Gagal membaca image: "
            f"{source}"
        )

    (
        detections,
        inference_ms,
    ) = engine.predict(
        frame
    )

    draw_detections(
        frame,
        detections,
    )

    print()
    print(
        f"[RESULT] Objects   : "
        f"{len(detections)}"
    )

    print(
        f"[RESULT] Inference : "
        f"{inference_ms:.2f} ms"
    )

    if output:

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        success = cv2.imwrite(
            str(output),
            frame,
        )

        if not success:

            raise RuntimeError(
                "Gagal menyimpan: "
                f"{output}"
            )

        print(
            f"[RESULT] Saved     : "
            f"{output}"
        )

    if show:

        cv2.imshow(
            "YOLOv8 - AMD DirectML",
            frame,
        )

        cv2.waitKey(0)

        cv2.destroyAllWindows()


def run_camera(
    engine: YOLODirectML,
    camera_id: int,
):

    cap = cv2.VideoCapture(
        camera_id,
        cv2.CAP_DSHOW,
    )

    if not cap.isOpened():

        cap.release()

        cap = cv2.VideoCapture(
            camera_id
        )

    if not cap.isOpened():

        raise RuntimeError(
            "Tidak bisa membuka "
            f"kamera {camera_id}"
        )

    print()
    print(
        "[CAMERA] Tekan Q atau ESC "
        "untuk keluar."
    )

    fps_ema = 0.0

    try:

        while True:

            loop_start = (
                time.perf_counter()
            )

            success, frame = (
                cap.read()
            )

            if not success:
                break

            (
                detections,
                inference_ms,
            ) = engine.predict(
                frame
            )

            draw_detections(
                frame,
                detections,
            )

            elapsed = max(
                time.perf_counter()
                - loop_start,
                1e-9,
            )

            fps_now = (
                1.0 / elapsed
            )

            if fps_ema == 0.0:
                fps_ema = fps_now

            else:
                fps_ema = (
                    0.9 * fps_ema
                    + 0.1 * fps_now
                )

            text = (
                f"FPS {fps_ema:.1f} | "
                f"DML {inference_ms:.1f} ms | "
                f"objects {len(detections)}"
            )

            cv2.putText(
                frame,
                text,
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

            cv2.imshow(
                "YOLOv8 - AMD DirectML",
                frame,
            )

            key = (
                cv2.waitKey(1)
                & 0xFF
            )

            if key in (
                ord("q"),
                27,
            ):
                break

    finally:

        cap.release()

        cv2.destroyAllWindows()


def main() -> int:

    parser = argparse.ArgumentParser(
        description=(
            "YOLOv8 detection "
            "via ONNX Runtime DirectML"
        )
    )

    parser.add_argument(
        "model",
        nargs="?",
        default="best.pt",
        help=(
            "Model .pt "
            "(default: best.pt)"
        ),
    )

    parser.add_argument(
        "--source",
        default="0",
        help=(
            "Camera index atau "
            "path image"
        ),
    )

    parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
    )

    parser.add_argument(
        "--conf",
        type=float,
        default=0.25,
    )

    parser.add_argument(
        "--iou",
        type=float,
        default=0.45,
    )

    parser.add_argument(
        "--output",
        help=(
            "Path output "
            "untuk image"
        ),
    )

    parser.add_argument(
        "--cpu",
        action="store_true",
    )

    parser.add_argument(
        "--force-export",
        action="store_true",
    )

    parser.add_argument(
        "--no-show",
        action="store_true",
    )

    args = parser.parse_args()

    engine = YOLODirectML(
        args.model,
        imgsz=args.imgsz,
        conf=args.conf,
        iou=args.iou,
        cpu=args.cpu,
        force_export=args.force_export,
    )

    source = (
        args.source.strip()
    )

    # Webcam.
    if source.isdigit():

        if args.no_show:

            raise ValueError(
                "--no-show tidak "
                "berguna untuk webcam "
                "karena tidak ada output."
            )

        run_camera(
            engine,
            int(source),
        )

        return 0

    source_path = Path(
        source
    )

    if not source_path.is_file():

        raise FileNotFoundError(
            "Source tidak ditemukan: "
            f"{source_path}"
        )

    if (
        source_path.suffix.lower()
        not in IMAGE_EXTENSIONS
    ):

        raise ValueError(
            "run_pt.py untuk "
            "image/webcam.\n"
            "Untuk video gunakan "
            "run_pt_video.py"
        )

    if args.output:

        output = Path(
            args.output
        )

    else:

        output = (
            Path("output")
            /
            (
                source_path.stem
                + "_detected"
                + source_path.suffix
            )
        )

    run_image(
        engine,
        source_path,
        output,
        show=not args.no_show,
    )

    return 0


if __name__ == "__main__":

    try:

        raise SystemExit(
            main()
        )

    except KeyboardInterrupt:

        print(
            "\n[STOP] "
            "Dihentikan user."
        )

        raise SystemExit(130)

    except Exception as exc:

        print(
            f"\n[ERROR] {exc}",
            file=sys.stderr,
        )

        raise SystemExit(1)