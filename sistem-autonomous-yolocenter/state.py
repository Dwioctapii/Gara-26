"""State tunggal, thread-safe, dengan skema yang kompatibel dengan client ZIP."""

from __future__ import annotations

import copy
import math
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
        self.live_frame_bgr = None
        self._frame_sequence = 0
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
            "buoy": {
                "detected": False,   # True jika buoy merah aktif terdeteksi
                "cx": 0,             # X center buoy di frame (pixel)
                "cy": 0,             # Y center buoy di frame (pixel)
                "x_target": 0,       # X target ideal di garis panduan (pixel)
                "error_px": 0.0,     # error = cx − x_target  (+ = kanan, − = kiri)
                "servo_pwm": 1500,   # PWM kemudi yang dihitung (µs)
                "pid": {"p": 0.0, "i": 0.0, "d": 0.0, "u": 0.0, "dt": 0.0},
            },
            # Channel komunikasi GUI → VisionWorker untuk hot-reload PID.
            # GUI increment _version saat SAVE → VisionWorker deteksi perubahan.
            "pid_config": {
                "kp": 2.0, "ki": 0.0, "kd": 0.0,
                "integral_limit": 100.0, "deadband": 5.0,
                "_version": 0,
            },
            # Status koneksi serial ke Teensy
            "serial": {
                "connected":   False,
                "port":        "",
                "error":       None,
                "last_pwm":    1500,
                "last_mode":   "DISCONNECTED",
                "last_mode_b": 0xFF,
            },
            "sensors": {"heartbeat": False, "eb": False, "pmb1": False, "pmb2": False, "manip": False, "thrusterPort": False, "thrusterStar": False, "ocs": False, "batPort": False, "batStar": False},
            "home": None, "lastCommand": None,
        }

    def update(self, patch: dict) -> None:
        with self.lock:
            _merge(self.data, patch)
            self.data["timestamp"] = time.time()

    def command(self, cmd: dict) -> None:
        name, action, patch = cmd.get("command"), cmd.get("action"), {"lastCommand": cmd}
        if name == "set_pid":
            values = {}
            limits = {
                "kp": (-1000.0, 1000.0),
                "ki": (-1000.0, 1000.0),
                "kd": (-1000.0, 1000.0),
                "deadband": (0.0, 1000.0),
                "integral_limit": (0.0, 1_000_000.0),
            }
            for key, (minimum, maximum) in limits.items():
                try:
                    value = float(cmd[key])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"PID {key} tidak valid") from exc
                if not math.isfinite(value) or not minimum <= value <= maximum:
                    raise ValueError(f"PID {key} di luar batas {minimum}..{maximum}")
                values[key] = value
            with self.lock:
                version = int(self.data["pid_config"].get("_version", 0)) + 1
                self.data["pid_config"].update(values, _version=version)
                self.data["lastCommand"] = cmd
                self.data["timestamp"] = time.time()
            return
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

    def pid_snapshot(self) -> dict:
        """Salinan kecil untuk hot-reload PID di loop vision berfrekuensi tinggi."""
        with self.lock:
            return dict(self.data["pid_config"])

    def set_live_frame(self, frame) -> None:
        with self.lock:
            self.live_frame_bgr = frame
            self._frame_sequence += 1

    def frame_snapshot(self):
        """Return frame copy + sequence; encoder dapat melewati frame duplikat."""
        with self.lock:
            if self.live_frame_bgr is None:
                return None, self._frame_sequence
            return self.live_frame_bgr.copy(), self._frame_sequence

    def replace_mission(self, waypoints: list[dict]) -> None:
        """Tukar mission sekaligus; client tidak akan menerima daftar setengah jadi."""
        with self.lock:
            self.data["mission"]["waypoints"] = waypoints
            self.data["mission"]["total"] = len(waypoints)
            self.data["timestamp"] = time.time()


store = StateStore()
