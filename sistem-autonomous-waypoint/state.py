"""State tunggal, thread-safe, dengan skema yang kompatibel dengan client ZIP."""

from __future__ import annotations

import copy
import threading
import time

from navigation import navigation_snapshot


def _merge(target: dict, patch: dict) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value


class StateStore:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.data = {
            "timestamp": time.time(), "connected": False, "lastError": None,
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
            "linear": {"x": 0.0, "y": 0.0, "z": 0.0},
            "angular": {"x": 0.0, "y": 0.0, "z": 0.0},
            "gps": {"lat": None, "lon": None, "sog": 0.0, "cog": 0.0, "satellites": 0, "hdop": 99.9, "fix": False},
            "speed": 0.0, "mode": "DISCONNECTED", "arm": "Disarmed",
            "battery1": {"voltage": 0.0, "current": 0.0, "percentage": 0},
            "thrusterPort": 0.0, "thrusterStar": 0.0, "depth": 0.0,
            "missionState": "IDLE", "loggerActive": False, "currentTrack": 1,
            "mission": {"current": 0, "total": 0, "waypoints": [], "revision": 0,
                        "syncing": False, "updatedAt": None},
            "navigation": {},
            "detection": {"label": "STANDBY", "foto_atas_ready": False, "foto_bawah_ready": False},
            "sensors": {"heartbeat": False, "gps": False, "imu": False,
                        "cameraAtas": False, "cameraBawah": False},
        }

    def update(self, patch: dict) -> None:
        with self.lock:
            _merge(self.data, patch)
            self.data["timestamp"] = time.time()

    def snapshot(self) -> dict:
        with self.lock:
            result = copy.deepcopy(self.data)
            gps, position = result["gps"], result["position"]
            # Alias lama tetap tersedia agar dashboard ZIP tidak perlu diubah.
            result.update({"lat": gps["lat"], "lon": gps["lon"],
                           "x": position["x"], "y": position["y"],
                           "sog": gps["sog"], "cog": gps["cog"],
                           "kompas": gps["cog"]})
            return result

    def replace_mission(self, waypoints: list[dict]) -> None:
        """Tukar mission sekaligus; client tidak akan menerima daftar setengah jadi."""
        with self.lock:
            self.data["mission"]["waypoints"] = waypoints
            self.data["mission"]["total"] = len(waypoints)
            self.data["mission"]["revision"] += 1
            self.data["mission"]["syncing"] = False
            self.data["mission"]["updatedAt"] = time.time()
            self._refresh_navigation()
            self.data["timestamp"] = time.time()

    def set_mission_syncing(self, syncing: bool) -> None:
        with self.lock:
            self.data["mission"]["syncing"] = syncing

    def refresh_navigation(self) -> None:
        with self.lock:
            self._refresh_navigation()

    def _refresh_navigation(self) -> None:
        self.data["navigation"] = navigation_snapshot(
            self.data["gps"], self.data["mission"]
        )


store = StateStore()
