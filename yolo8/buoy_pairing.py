"""Geometri pasangan buoy merah-hijau untuk navigasi ASV.

Modul ini sengaja tidak bergantung pada OpenCV/YOLO supaya perhitungan dapat
diuji terpisah dari inference dan tampilan video.

KONTRAK PEMILIHAN TARGET -- JANGAN DIUBAH TANPA MEMPERBARUI TEST:

1. Hanya kelas buoy merah/hijau yang boleh menjadi pasangan. ``boxgreen`` dan
   kelas lain bukan buoy.
2. ``focus_side`` adalah posisi HIJAU RELATIF TERHADAP MERAH. Nilai ini bukan
   filter separuh kiri/kanan gambar.
3. Kedalaman visual dibandingkan memakai dasar bbox (Y2), bukan midpoint Y,
   bukan X, dan bukan hasil estimasi meter.
4. OpenCV mempunyai Y=0 di atas. Karena itu Y2 paling BESAR berarti objek
   terlihat paling BAWAH/paling DEPAN.
5. Candidate pairing diproses dari ``front_y`` terbesar. Hal ini wajib agar
   detection belakang tidak lebih dulu mencuri buoy milik gerbang depan.
6. Target akhir dipilih global dari semua pair valid. Tidak boleh membuang
   target hanya karena midpoint melintasi pusat frame.
7. Jarak meter dipakai untuk telemetry dan tie-break saja. Jarak meter tidak
   boleh mengalahkan urutan ``front_y`` dalam pemilihan target.
8. Main loop memilih target tepat satu kali, lalu mengirim object pair yang
   sama ke payload dan drawing.
"""

from __future__ import annotations

import math


GREEN_NAMES = {"buoygreen", "greenbuoy", "buoyhijau", "hijaubuoy"}
RED_NAMES = {"buoyred", "redbuoy", "buoymerah", "merahbuoy"}


def _compact_name(value: object) -> str:
    """Normalisasi nama kelas tanpa menganggap ``boxgreen`` sebagai buoy."""

    return "".join(character for character in str(value).lower() if character.isalnum())


def buoy_color(detection: dict) -> str | None:
    """Kembalikan ``green``/``red`` hanya untuk kelas buoy yang dikenal."""

    name = _compact_name(detection.get("class_name", ""))

    if name in GREEN_NAMES:
        return "green"
    if name in RED_NAMES:
        return "red"

    return None


def bbox_center(detection: dict) -> tuple[float, float]:
    """Titik pusat bbox sebagai float; jangan dibulatkan ke pixel integer."""

    x1, y1, x2, y2 = map(float, detection["box"])
    return (x1 + x2) * 0.5, (y1 + y2) * 0.5


def focal_length_pixels(frame_width: int, horizontal_fov_degrees: float) -> float:
    """Hitung focal length horizontal dalam pixel dari FOV kamera."""

    if frame_width <= 0:
        raise ValueError("frame_width harus > 0")
    if not 0.0 < horizontal_fov_degrees < 180.0:
        raise ValueError("horizontal_fov_degrees harus di antara 0 dan 180")

    half_fov = math.radians(horizontal_fov_degrees * 0.5)
    return (frame_width * 0.5) / math.tan(half_fov)


def normalize_focus_side(focus_side: str | None) -> str | None:
    """Normalisasi mode orientasi pasangan.

    PENTING: ``right`` dan ``left`` TIDAK berarti separuh kanan/kiri frame.
    Mode menyatakan posisi BUOY HIJAU relatif terhadap BUOY MERAH:

    - ``right``: pusat buoy hijau harus berada di kanan pusat buoy merah.
    - ``left``: pusat buoy hijau harus berada di kiri pusat buoy merah.

    Karena acuannya adalah buoy pasangannya sendiri, gerbang boleh bergerak
    melewati tengah frame tanpa dibuang dan tanpa membuat target lompat ke
    gerbang yang lebih belakang.
    """

    if focus_side is None:
        return None

    side = str(focus_side).strip().lower()
    aliases = {
        "right": "right",
        "kanan": "right",
        "left": "left",
        "kiri": "left",
    }

    if side not in aliases:
        raise ValueError(
            'focus_side harus "right"/"kanan" atau "left"/"kiri"'
        )

    return aliases[side]


def frontmost_pair(pairs: list[dict]) -> dict | None:
    """Ambil tepat satu pasangan yang paling depan di SELURUH frame.

    OpenCV memakai titik (0, 0) di kiri atas. Artinya nilai Y bertambah ketika
    posisi bergerak ke bawah. Pada kamera ASV yang sejajar permukaan air,
    pasangan paling dekat secara visual adalah pasangan dengan dasar bbox
    rata-rata (``front_y``) paling besar.

    Tidak ada filter berdasarkan posisi midpoint terhadap tengah frame.
    ``distance_m`` hanya menjadi tie-break apabila ``front_y`` sama persis.
    """

    if not pairs:
        return None

    return max(
        pairs,
        key=lambda pair: (
            float(pair["front_y"]),
            -float(pair["distance_m"]),
        ),
    )


def pair_buoys(
    detections: list[dict],
    frame_width: int,
    frame_height: int,
    known_pair_width_m: float = 2.0,
    horizontal_fov_degrees: float = 90.0,
    max_vertical_gap_ratio: float = 0.20,
    focus_side: str | None = None,
) -> list[dict]:
    """Pasangkan buoy hijau-merah dan hitung geometri gerbangnya.

    Satu detection hanya boleh masuk satu pasangan. Kandidat paling depan
    selalu diamankan lebih dahulu; kemiripan posisi vertikal dan ukuran bbox
    menjadi urutan kedua untuk kandidat dengan kedalaman serupa.

    ``forward_distance_m`` adalah jarak tegak lurus kamera ke garis pasangan.
    ``distance_m`` adalah jarak miring kapal/kamera ke titik tengah pasangan.
    Model ini mengasumsikan kedua buoy berada pada permukaan air dan bentang
    antarpusatnya adalah ``known_pair_width_m``.
    """

    if frame_height <= 0:
        raise ValueError("frame_height harus > 0")
    if known_pair_width_m <= 0:
        raise ValueError("known_pair_width_m harus > 0")
    if not 0.0 <= max_vertical_gap_ratio <= 1.0:
        raise ValueError("max_vertical_gap_ratio harus di antara 0 dan 1")

    # Validasi mode sekali saja sebelum memproses kandidat. Nilai None berguna
    # untuk pengujian geometri generik; aplikasi utama selalu mengirim mode.
    normalized_side = normalize_focus_side(focus_side)

    focal_px = focal_length_pixels(frame_width, horizontal_fov_degrees)
    greens = [index for index, item in enumerate(detections) if buoy_color(item) == "green"]
    reds = [index for index, item in enumerate(detections) if buoy_color(item) == "red"]
    # Tuple kandidat sengaja diawali dengan -front_y. sorted() bekerja naik,
    # sehingga nilai Y terbesar (paling bawah/paling depan) diproses DAHULU.
    # Ini mencegah pasangan belakang yang bottom-gap-nya kebetulan lebih rapi
    # mengambil detection merah/hijau milik pasangan paling depan.
    candidates: list[tuple[float, float, int, int]] = []
    max_vertical_gap_px = frame_height * max_vertical_gap_ratio

    for green_index in greens:
        green = detections[green_index]
        green_x, green_y = bbox_center(green)
        _, green_y1, _, green_y2 = map(float, green["box"])
        green_height = max(green_y2 - green_y1, 1.0)

        for red_index in reds:
            red = detections[red_index]
            red_x, red_y = bbox_center(red)
            _, red_y1, _, red_y2 = map(float, red["box"])
            red_height = max(red_y2 - red_y1, 1.0)

            # Mode kanan/kiri adalah ORIENTASI DALAM PASANGAN, bukan lokasi di
            # frame. Gerbang kanan tetap valid walaupun midpoint-nya di kiri.
            if normalized_side == "right" and green_x <= red_x:
                continue
            if normalized_side == "left" and green_x >= red_x:
                continue

            # Dasar bbox lebih mewakili garis air/depth daripada pusat bbox.
            vertical_gap = abs(green_y2 - red_y2)

            average_height = (green_height + red_height) * 0.5

            # Batas lama sebesar 20% tinggi frame terlalu longgar: pada 480p
            # nilainya 96 px dan dapat memasangkan buoy depan dengan buoy jauh.
            # Batas efektif juga diikat ke tinggi kedua buoy. Minimum 6 px
            # menoleransi jitter YOLO pada detection kecil di kejauhan.
            relative_vertical_limit = max(6.0, average_height * 1.75)
            effective_vertical_limit = min(
                max_vertical_gap_px,
                relative_vertical_limit,
            )

            if vertical_gap > effective_vertical_limit:
                continue

            size_difference = abs(math.log(green_height / red_height))
            pixel_distance = math.hypot(red_x - green_x, red_y - green_y)

            if pixel_distance <= 0.0:
                continue

            # Score tidak memilih depan/belakang. Score hanya mengurutkan mutu
            # kandidat setelah front_y, agar pasangan dengan depth yang sama
            # memilih bottom-gap dan skala bbox yang lebih konsisten.
            score = (
                vertical_gap / average_height
                + 0.5 * size_difference
                + 0.05 * pixel_distance / frame_width
            )
            front_y = (green_y2 + red_y2) * 0.5
            candidates.append((-front_y, score, green_index, red_index))

    used_greens: set[int] = set()
    used_reds: set[int] = set()
    pairs: list[dict] = []

    # Greedy tetap one-to-one, tetapi urutannya sekarang tegas: DEPAN dahulu,
    # baru kualitas pasangan. Ini adalah invariannya; jangan balik urutan key.
    for _, _, green_index, red_index in sorted(candidates):
        if green_index in used_greens or red_index in used_reds:
            continue

        green_center = bbox_center(detections[green_index])
        red_center = bbox_center(detections[red_index])
        green_bottom_y = float(detections[green_index]["box"][3])
        red_bottom_y = float(detections[red_index]["box"][3])
        delta_x = red_center[0] - green_center[0]
        delta_y = red_center[1] - green_center[1]
        pixel_distance = math.hypot(delta_x, delta_y)
        midpoint_x = (green_center[0] + red_center[0]) * 0.5
        midpoint_y = (green_center[1] + red_center[1]) * 0.5
        front_y = (green_bottom_y + red_bottom_y) * 0.5

        # Similar-triangle/pinhole-camera model:
        # Z = lebar_nyata * focal_px / lebar_dalam_pixel.
        forward_distance_m = known_pair_width_m * focal_px / pixel_distance
        midpoint_offset_m = (
            (midpoint_x - frame_width * 0.5) * forward_distance_m / focal_px
        )
        distance_m = math.hypot(forward_distance_m, midpoint_offset_m)
        bearing_degrees = math.degrees(
            math.atan2(midpoint_x - frame_width * 0.5, focal_px)
        )

        def endpoint_distance(center_x: float) -> float:
            lateral_m = (
                (center_x - frame_width * 0.5) * forward_distance_m / focal_px
            )
            return math.hypot(forward_distance_m, lateral_m)

        # Semua nilai geometri target disimpan dalam satu object pair. Main
        # loop tidak boleh menghitung midpoint/front_y lagi dengan rumus lain.
        pairs.append(
            {
                "green_index": green_index,
                "red_index": red_index,
                "green_center": green_center,
                "red_center": red_center,
                "midpoint": (midpoint_x, midpoint_y),
                "front_y": front_y,
                "pixel_distance": pixel_distance,
                "horizontal_pixel_distance": abs(delta_x),
                "vertical_pixel_distance": abs(delta_y),
                "known_width_m": known_pair_width_m,
                "focal_length_px": focal_px,
                "forward_distance_m": forward_distance_m,
                "distance_m": distance_m,
                "green_distance_m": endpoint_distance(green_center[0]),
                "red_distance_m": endpoint_distance(red_center[0]),
                "bearing_degrees": bearing_degrees,
            }
        )
        used_greens.add(green_index)
        used_reds.add(red_index)

    # ID dibuat deterministik dari kiri ke kanan agar tidak berubah hanya
    # karena confidence/score kandidat bergeser sedikit antarframe.
    pairs.sort(key=lambda pair: pair["midpoint"][0])
    for pair_id, pair in enumerate(pairs, start=1):
        pair["id"] = pair_id

    return pairs
