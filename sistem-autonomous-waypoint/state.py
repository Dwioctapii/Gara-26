"""State tunggal, thread-safe, dengan skema yang kompatibel dengan client ZIP."""

from __future__ import annotations

import base64
import copy
import threading
import time


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
            "battery1": {"voltage": 0.0, "current": 0.0, "pressure": 0, "capacity": 0, "used": 0.0, "temp": 0},
            "thrusterPort": {"voltage": 0.0, "current": 0.0, "capacity": 0, "temp": 0},
            "thrusterStar": {"voltage": 0.0, "current": 0.0, "capacity": 0, "temp": 0},
            "gps": {"lat": None, "lon": None, "sog": 0.0, "cog": 0.0, "satellites": 0, "hdop": 99.9, "fix": False, "lastCalib": "-"},
            "speed": 0.0, "depth": 0.0, "mode": "DISCONNECTED", "arm": "Disarmed",
            "missionState": "IDLE", "loggerActive": False, "currentTrack": "A",
            "mission": {"current": 0, "total": 0, "waypoints": []},
            "servo": [0, 0, 0, 0],
            "detection": {"label": "STANDBY", "foto_atas_ready": False, "foto_bawah_ready": False},
            "photos": {"atas": None, "bawah": None},
            "sensors": {"heartbeat": False, "eb": False, "pmb1": False, "pmb2": False, "manip": False, "thrusterPort": False, "thrusterStar": False, "ocs": False, "batPort": False, "batStar": False},
            "home": None, "lastCommand": None,
        }

    def update(self, patch: dict) -> None:
        with self.lock:
            _merge(self.data, patch)
            self.data["timestamp"] = time.time()

    def command(self, cmd: dict) -> None:
        name, action, patch = cmd.get("command"), cmd.get("action"), {"lastCommand": cmd}
        if name == "set_mode" and cmd.get("mode") in {"Manual", "Auto", "Return Home"}: patch["mode"] = cmd["mode"]
        elif name == "arm" and action in {"arm", "disarm", "estop"}: patch["arm"] = {"arm":"Armed","disarm":"Disarmed","estop":"EStop"}[action]
        elif name == "mission" and action in {"start", "pause", "stop"}: patch["missionState"] = {"start":"RUNNING","pause":"PAUSED","stop":"STOPPED"}[action]
        elif name == "reset_mission": patch.update(missionState="IDLE", mission={"current": 0, "total": self.data["mission"].get("total", 0), "waypoints": self.data["mission"].get("waypoints", [])})
        elif name == "set_track" and cmd.get("track") in ("A", "B", "C", "D"): patch["currentTrack"] = cmd["track"]
        elif name == "go_home": patch.update(mode="Return Home", missionState="RETURNING HOME")
        elif name == "hold_position": patch["missionState"] = "HOLDING"
        elif name == "set_home": patch["home"] = {k:self.data["gps"][k] for k in ("lat","lon")}
        elif name == "calibration": patch["gps"] = {"lastCalib": time.strftime("%F %T")}
        elif name == "logger" and action in {"start", "stop"}:
            patch["loggerActive"] = action == "start"
        self.update(patch)

    def snapshot(self) -> dict:
        with self.lock:
            out = copy.deepcopy(self.data)
        gps, pos = out["gps"], out["position"]
        out.update(lat=gps["lat"], lon=gps["lon"], x=pos["x"], y=pos["y"], sog=gps["sog"], cog=gps["cog"], kompas=gps["cog"])
        return out

    def set_photo(self, camera: str, jpeg: bytes) -> None:
        if camera not in ("atas", "bawah"):
            raise ValueError(f"kamera tidak dikenal: {camera}")
        self.update({"photos": {camera: base64.b64encode(jpeg).decode("ascii")}})

    def clear_photos(self) -> None:
        self.update({
            "photos": {"atas": None, "bawah": None},
            "detection": {"label": "STANDBY", "foto_atas_ready": False, "foto_bawah_ready": False},
        })

    def replace_mission(self, waypoints: list[dict]) -> None:
        """Tukar mission sekaligus; client tidak akan menerima daftar setengah jadi."""
        with self.lock:
            self.data["mission"]["waypoints"] = waypoints
            self.data["mission"]["total"] = len(waypoints)
            self.data["timestamp"] = time.time()


store = StateStore()
