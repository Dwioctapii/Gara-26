"""Model data dan parser kontrak WebSocket milik proses YOLOv8."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class TargetObservation:
    pair_id: int
    bearing_degrees: float
    distance_m: float
    midpoint_x: float | None = None
    confidence: float | None = None


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} harus berupa angka")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} harus berupa angka") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} harus finite")
    return number


def parse_yolo_target(payload: dict) -> TargetObservation | None:
    """Ambil satu target resmi dari payload ``yolo8/run_pt_video.py``.

    Target tidak dipilih ulang di sini. ID yang sudah dipilih YOLO merupakan
    satu-satunya sumber kebenaran agar gambar, WebSocket, dan kontrol kapal
    mengacu pada pasangan buoy yang sama.
    """

    if not isinstance(payload, dict):
        raise ValueError("payload YOLO harus berupa object JSON")

    target_id = payload.get("target_pair_id")
    pairs = payload.get("pairs", [])
    if target_id is None:
        return None
    if not isinstance(pairs, list):
        raise ValueError("pairs harus berupa array")

    target = next(
        (
            pair
            for pair in pairs
            if isinstance(pair, dict) and pair.get("id") == target_id
        ),
        None,
    )
    if target is None:
        raise ValueError(f"target_pair_id {target_id!r} tidak ada di pairs")

    pair_id = int(_finite_number(target_id, "target_pair_id"))
    bearing = _finite_number(target.get("bearing_degrees"), "bearing_degrees")
    distance = _finite_number(target.get("distance"), "distance")
    if distance < 0.0:
        raise ValueError("distance tidak boleh negatif")

    midpoint_x_value = target.get("midpoint_x")
    midpoint_x = (
        None
        if midpoint_x_value is None
        else _finite_number(midpoint_x_value, "midpoint_x")
    )

    confidences = [
        _finite_number(buoy.get("confidence"), "confidence")
        for buoy in payload.get("buoys", [])
        if isinstance(buoy, dict) and buoy.get("pair_id") == target_id
    ]
    confidence = min(confidences) if confidences else None

    return TargetObservation(
        pair_id=pair_id,
        bearing_degrees=bearing,
        distance_m=distance,
        midpoint_x=midpoint_x,
        confidence=confidence,
    )

