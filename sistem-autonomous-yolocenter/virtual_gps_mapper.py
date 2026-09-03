"""
Konversi koordinat antara sistem virtual (30×30 meter) dan GPS (lat/lon).

Prinsip:
  - Virtual map: sumbu Y = arah depan kapal (heading), sumbu X = tegak lurus ke kanan.
  - Satu unit virtual = 1 meter.
  - Titik origin (0,0) virtual dipetakan ke GPS awal.
  - Rotasi mengikuti heading kompas saat kalibrasi.

Rumus:
  v = R * (gps - gps_awal)  (GPS → Virtual)
  g = gps_awal + R⁻¹ * v    (Virtual → GPS)

Dimana R adalah matriks rotasi berdasarkan heading.
"""

import math


class VirtualGPSMapper:
    """
    Mapper koordinat virtual ↔ GPS dengan rotasi berdasarkan heading.

    Parameter konstruktor:
        virtual_origin : tuple[float, float]  → (x, y) virtual awal (biasanya 0,0)
        gps_origin     : tuple[float, float]  → (lat, lon) GPS awal
        heading_deg    : float                → heading kompas saat kalibrasi (derajat)

    Method:
        virtual_to_gps(x_virtual, y_virtual) → (lat, lon)
        gps_to_virtual(lat, lon)             → (x_virtual, y_virtual)
    """

    def __init__(self, virtual_origin: tuple[float, float],
                 gps_origin: tuple[float, float],
                 heading_deg: float):
        """
        Inisialisasi mapper dengan titik acuan.

        Args:
            virtual_origin: (x, y) di peta virtual (biasanya 0,0)
            gps_origin: (lat, lon) di dunia nyata
            heading_deg: arah depan kapal (0° = Utara, 90° = Timur)
        """
        self.vx0, self.vy0 = virtual_origin
        self.glat0, self.glon0 = gps_origin

        # Konversi heading ke radian
        self.heading_rad = math.radians(heading_deg)

        # Pre-komputasi matriks rotasi dan inversnya
        # Matriks rotasi: [cos θ  -sin θ]
        #                 [sin θ   cos θ]
        cos_h = math.cos(self.heading_rad)
        sin_h = math.sin(self.heading_rad)

        # Rotasi R (virtual → GPS)
        self.R = ((cos_h, -sin_h),
                  (sin_h,  cos_h))

        # Rotasi invers R⁻¹ (GPS → virtual)
        self.R_inv = ((cos_h,  sin_h),
                      (-sin_h, cos_h))

        # Konstanta konversi meter ↔ derajat GPS (perkiraan)
        # 1° latitude ≈ 111,320 meter (konstan)
        # 1° longitude ≈ 111,320 * cos(lat) meter (bervariasi)
        self.METERS_PER_DEG_LAT = 111320.0
        self.METERS_PER_DEG_LON = 111320.0 * math.cos(math.radians(self.glat0))

    def _meters_to_deg(self, dx_m: float, dy_m: float) -> tuple[float, float]:
        """Konversi selisih meter ke selisih derajat GPS."""
        dlat = dy_m / self.METERS_PER_DEG_LAT
        dlon = dx_m / self.METERS_PER_DEG_LON
        return dlat, dlon

    def _deg_to_meters(self, dlat: float, dlon: float) -> tuple[float, float]:
        """Konversi selisih derajat GPS ke meter."""
        dx_m = dlon * self.METERS_PER_DEG_LON
        dy_m = dlat * self.METERS_PER_DEG_LAT
        return dx_m, dy_m

    def virtual_to_gps(self, x_virtual: float, y_virtual: float) -> tuple[float, float]:
        """
        Konversi koordinat virtual (x, y) ke GPS (lat, lon).

        Rumus:
            1. Hitung selisih virtual dari origin: (dx, dy) = (x - vx0, y - vy0)
            2. Rotasikan menggunakan matriks R (karena sumbu Y = arah heading)
            3. Konversi meter → derajat GPS
            4. Tambahkan ke GPS origin

        Args:
            x_virtual: koordinat X di peta virtual (meter)
            y_virtual: koordinat Y di peta virtual (meter)

        Returns:
            (latitude, longitude)
        """
        # 1. Selisih dari origin virtual
        dx = x_virtual - self.vx0
        dy = y_virtual - self.vy0

        # 2. Rotasi (virtual → GPS)
        # Perhatikan: Y virtual = arah depan, X virtual = ke kanan
        # Rotasi standar: X' = cos*dx - sin*dy, Y' = sin*dx + cos*dy
        # Tapi karena Y = arah depan (Utara), maka:
        #   Δlon (Timur)  = cos*dx - sin*dy
        #   Δlat (Utara)  = sin*dx + cos*dy
        dlon_m = self.R[0][0] * dx + self.R[0][1] * dy
        dlat_m = self.R[1][0] * dx + self.R[1][1] * dy

        # 3. Konversi meter → derajat GPS
        dlat, dlon = self._meters_to_deg(dlon_m, dlat_m)

        # 4. Tambahkan ke GPS origin
        lat = self.glat0 + dlat
        lon = self.glon0 + dlon

        return lat, lon

    def gps_to_virtual(self, lat: float, lon: float) -> tuple[float, float]:
        """
        Konversi koordinat GPS (lat, lon) ke virtual (x, y).

        Rumus:
            1. Hitung selisih GPS dari origin: (dlat, dlon)
            2. Konversi derajat → meter
            3. Rotasikan menggunakan matriks invers R⁻¹ (karena sumbu Y = arah heading)
            4. Tambahkan ke virtual origin

        Args:
            lat: latitude
            lon: longitude

        Returns:
            (x_virtual, y_virtual)
        """
        # 1. Selisih dari GPS origin
        dlat = lat - self.glat0
        dlon = lon - self.glon0

        # 2. Konversi derajat → meter
        dx_m, dy_m = self._deg_to_meters(dlat, dlon)

        # 3. Rotasi invers (GPS → virtual)
        #   X_virtual = cos*dx_m + sin*dy_m
        #   Y_virtual = -sin*dx_m + cos*dy_m
        x_rel = self.R_inv[0][0] * dx_m + self.R_inv[0][1] * dy_m
        y_rel = self.R_inv[1][0] * dx_m + self.R_inv[1][1] * dy_m

        # 4. Tambahkan ke virtual origin
        x_virtual = self.vx0 + x_rel
        y_virtual = self.vy0 + y_rel

        return x_virtual, y_virtual

    def get_heading(self) -> float:
        """Kembalikan heading dalam derajat."""
        return math.degrees(self.heading_rad)

    def set_heading(self, heading_deg: float) -> None:
        """Update heading (gunakan saat kapal berubah orientasi)."""
        self.heading_rad = math.radians(heading_deg)
        cos_h = math.cos(self.heading_rad)
        sin_h = math.sin(self.heading_rad)
        self.R = ((cos_h, -sin_h),
                  (sin_h,  cos_h))
        self.R_inv = ((cos_h,  sin_h),
                      (-sin_h, cos_h))

