from __future__ import annotations

import copy
from typing import TypedDict, Any


PANJANG_KAPAL = 1.04
LEBAR_KAPAL = 0.52
RADIUS_BUOY = 0.15
MARGIN_NAVIGASI = 0.30
SETENGAH_LEBAR_GATE_MINIMUM = LEBAR_KAPAL * 0.5 + RADIUS_BUOY + MARGIN_NAVIGASI

LEBAR_ARENA = 30.0
TINGGI_ARENA = 30.0
JARAK_PASANGAN_BUOY = 2.0
UKURAN_PETA_PERENCANAAN = 35.0
RESOLUSI_GRID = 0.5


def _titik(x: float, y: float) -> dict[str, float]:
    return {"x": float(x), "y": float(y)}


def _cerminkan_arena(arena: dict[str, Any]) -> dict[str, Any]:
    hasil = copy.deepcopy(arena)
    hasil["nama"] = "B"

    hasil["titik_mulai"]["x"] = LEBAR_ARENA - hasil["titik_mulai"]["x"]

    for titik in hasil["kotak"].values():
        titik["x"] = LEBAR_ARENA - titik["x"]

    for daftar_titik in hasil["buoy"].values():
        for titik in daftar_titik:
            titik["x"] = LEBAR_ARENA - titik["x"]

    for titik in hasil["docking"]:
        titik["x"] = LEBAR_ARENA - titik["x"]

    return hasil


DEFAULT_ARENA_A: dict[str, Any] = {
    "nama": "A",
    "titik_mulai": _titik(20.5, 0.0),
    "dimensi": {
        "lebar_arena": LEBAR_ARENA,
        "tinggi_arena": TINGGI_ARENA,
        "panjang_kapal": PANJANG_KAPAL,
        "lebar_kapal": LEBAR_KAPAL,
        "radius_buoy": RADIUS_BUOY,
        "margin_navigasi": MARGIN_NAVIGASI,
        "setengah_lebar_gate_minimum": SETENGAH_LEBAR_GATE_MINIMUM,
        "jarak_pasangan_buoy": JARAK_PASANGAN_BUOY,
        "ukuran_peta_perencanaan": UKURAN_PETA_PERENCANAAN,
        "resolusi_grid": RESOLUSI_GRID,
    },
    "kotak": {
        "merah": _titik(20.5, 0.0),
        "hijau": _titik(5.5, 1.0),
        "biru": _titik(2.5, 4.0),
    },
    "buoy": {
        "merah": [
            _titik(20.0, 7.0),
            _titik(18.7, 10.0),
            _titik(20.5, 12.6),
            _titik(14.5, 18.5),
            _titik(12.5, 18.5),
            _titik(10.5, 18.5),
            _titik(8.5, 18.5),
            _titik(1.5, 15.0),
            _titik(0.0, 11.5),
            _titik(0.0, 7.5),
        ],
        "hijau": [
            _titik(21.5, 7.0),
            _titik(20.2, 10.0),
            _titik(22.1, 12.6),
            _titik(14.5, 20.0),
            _titik(12.5, 20.0),
            _titik(10.5, 20.0),
            _titik(8.5, 20.0),
            _titik(3.0, 15.0),
            _titik(1.3, 11.5),
            _titik(1.3, 7.5),
        ],
    },
    "docking": [
        _titik(19.8, 1.0),
        _titik(20.5, 1.0),
        _titik(21.2, 1.0),
    ],
}

DEFAULT_ARENA_B: dict[str, Any] = _cerminkan_arena(DEFAULT_ARENA_A)

# Salinan aktif ini boleh berubah tanpa mengubah data default.
ARENA_A: dict[str, Any] = copy.deepcopy(DEFAULT_ARENA_A)
ARENA_B: dict[str, Any] = copy.deepcopy(DEFAULT_ARENA_B)

# --- SKEMA DATA DINGIN (Disimpan ke File JSON) ---
DEFAULT_CONFIG: dict[str, Any] = {
    "pid_config": {
        "kp": 2.0,
        "ki": 0.0,
        "kd": 0.0,
        "integral_limit": 100.0,
        "deadband": 5.0,
        "_version": 0,
    },
    "currentTrack": "A",
    "missionState": "IDLE",
    "home": None,
    "loggerActive": False,
    "tahan_foto": False,
    "mission": {
        "waypoints": []
    },
    "arena": {
        "A": copy.deepcopy(ARENA_A),
        "B": copy.deepcopy(ARENA_B),
        "posisi_acuan": None,
        "set_dock_sekarang": None,
        "acuan_terkunci": False,
    },
    "foto": {
        "atas": {"tersedia": False, "revisi": 0},
        "bawah": {"tersedia": False, "revisi": 0}
    }
}

# --- SKEMA DATA PANAS (Hanya di Memori / RAM) ---
DEFAULT_HOT_DATA: dict[str, Any] = {
    "timestamp": 0.0,
    "connected": False,
    "lastError": None,
    "position": {"x": 0.0, "y": 0.0, "z": 0.0},
    "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
    "linear": {"x": 0.0, "y": 0.0, "z": 0.0},
    "angular": {"x": 0.0, "y": 0.0, "z": 0.0},
    "battery1": {"voltage": 0.0, "current": 0.0, "pressure": 0, "capacity": 0, "used": 0.0, "temp": 0},
    "thrusterPort": {"voltage": 0.0, "current": 0.0, "capacity": 0, "temp": 0},
    "thrusterStar": {"voltage": 0.0, "current": 0.0, "capacity": 0, "temp": 0},
    "gps": {
        "lat": None,
        "lon": None,
        "sog": 0.0,
        "cog": 0.0,
        "satellites": 0,
        "hdop": 99.9,
        "fix": False,
        "lastCalib": "-",
    },
    "speed": 0.0,
    "depth": 0.0,
    "mode": "DISCONNECTED",
    "arm": "Disarmed",
    "missionState": "IDLE",
    "mission": {"current": 0, "total": 0}, # waypoints disimpan di config
    "servo": [0, 0, 0, 0],
    "detection": {
        "label": "STANDBY",
        "area_green": 0,
        "area_blue": 0
    },
    "buoy": {
        "detected": False,
        "mode": "NONE",
        "cx": 0,
        "cy": 0,
        "cx_red": 0,
        "cx_green": 0,
        "x_target": 0,
        "error_px": 0.0,
        "servo_pwm": 1500,
        "pid": {"p": 0.0, "i": 0.0, "d": 0.0, "u": 0.0, "dt": 0.0},
    },
    "serial": {
        "connected": False,
        "port": "",
        "error": None,
        "last_pwm": 1500,
        "last_mode": "DISCONNECTED",
        "last_mode_b": 0xFF,
    },
    "sensors": {
        "heartbeat": False, "eb": True, "pmb1": True, "pmb2": True, "manip": True,
        "thrusterPort": True, "thrusterStar": True, "ocs": True, "batPort": True, "batStar": True
    },
    "lastCommand": None,
}
