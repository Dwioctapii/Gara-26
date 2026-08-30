"""Estimasi jarak kamera-ke-objek dari lebar object dalam pixel.

KONTRAK RUMUS:

    distance_m = object_width_m * focal_length_px / bbox_width_px

Unit sengaja ditulis eksplisit pada nama parameter:

- panjang objek diberikan lewat ``object_width_cm``;
- focal length kamera diberikan dalam pixel;
- lebar bbox berasal langsung dari koordinat float YOLO;
- hasil selalu meter.

Contoh untuk buoy selebar 35 cm, focal length 200 px, dan bbox 5 px:

    (35 / 100) * 200 / 5 = 14 meter

Angka 35 TIDAK boleh dianggap 35 meter. Pemisahan unit ini mencegah hasil
1.400 meter yang muncul ketika 35 cm salah diperlakukan sebagai 35 m.
"""

from __future__ import annotations


CM_PER_METER = 100.0


def bbox_width_pixels(bbox) -> float:
    """Ambil lebar bbox float tanpa pembulatan gambar OpenCV."""

    x1, _, x2, _ = map(float, bbox)
    return x2 - x1


def estimate_camera_distance_m(
    bbox,
    object_width_cm: float,
    focal_length_px: float,
) -> float | None:
    """Hitung jarak kamera-ke-objek dalam meter memakai pinhole model."""

    if object_width_cm <= 0:
        raise ValueError("object_width_cm harus > 0")
    if focal_length_px <= 0:
        raise ValueError("focal_length_px harus > 0")

    width_px = bbox_width_pixels(bbox)
    if width_px <= 0:
        return None

    object_width_m = object_width_cm / CM_PER_METER
    return object_width_m * focal_length_px / width_px


def average_valid_distances(*distances: float | None) -> float | None:
    """Rata-rata nilai valid; dipakai hanya untuk midpoint suatu pasangan."""

    valid = [distance for distance in distances if distance is not None]
    return sum(valid) / len(valid) if valid else None
