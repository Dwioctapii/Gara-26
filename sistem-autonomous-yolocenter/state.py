"""State tunggal, thread-safe, dengan skema yang kompatibel dengan client ZIP."""

from __future__ import annotations

import copy
import math
import threading
import time
import json
import hashlib
from pathlib import Path


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
            "detection": {"label": "STANDBY", "foto_atas_ready": False, "foto_bawah_ready": False,
                          "area_green": 0, "area_blue": 0},
            "buoy": {
                "detected": False,
                "cx": 0,
                "cy": 0,
                "x_target": 0,
                "error_px": 0.0,
                "servo_pwm": 1500,
                "pid": {"p": 0.0, "i": 0.0, "d": 0.0, "u": 0.0, "dt": 0.0},
            },
            "pid_config": {
                "kp": 2.0, "ki": 0.0, "kd": 0.0,
                "integral_limit": 100.0, "deadband": 5.0,
                "_version": 0,
            },
            "serial": {
                "connected": False,
                "port": "",
                "error": None,
                "last_pwm": 1500,
                "last_mode": "DISCONNECTED",
                "last_mode_b": 0xFF,
            },
            "sensors": {"heartbeat": False, "eb": False, "pmb1": False, "pmb2": False, "manip": False,
                        "thrusterPort": False, "thrusterStar": False, "ocs": False, "batPort": False, "batStar": False},
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

        if name == "set_mode" and cmd.get("mode") in {"Manual", "Auto", "Return Home"}:
            patch["mode"] = cmd["mode"]
        elif name == "arm" and action in {"arm", "disarm", "estop"}:
            patch["arm"] = {"arm": "Armed", "disarm": "Disarmed", "estop": "EStop"}[action]
        elif name == "mission" and action in {"start", "pause", "stop"}:
            patch["missionState"] = {"start": "RUNNING", "pause": "PAUSED", "stop": "STOPPED"}[action]
        elif name == "reset_mission":
            patch.update(missionState="IDLE", mission={"current": 0, "total": self.data["mission"].get("total", 0),
                                                       "waypoints": self.data["mission"].get("waypoints", [])})
        elif name == "set_track" and cmd.get("track") in ("A", "B", "C", "D"):
            patch["currentTrack"] = cmd["track"]
        elif name == "go_home":
            patch.update(mode="Return Home", missionState="RETURNING HOME")
        elif name == "hold_position":
            patch["missionState"] = "HOLDING"
        elif name == "set_home":
            patch["home"] = {k: self.data["gps"][k] for k in ("lat", "lon")}
        elif name == "calibration":
            patch["gps"] = {"lastCalib": time.strftime("%F %T")}
        elif name == "logger" and action in {"start", "stop"}:
            patch["loggerActive"] = action == "start"
        elif name == "reset_photo":
            patch["detection"] = {
                "label": "STANDBY",
                "foto_atas_ready": False,
                "foto_bawah_ready": False,
            }
        self.update(patch)

    def snapshot(self) -> dict:
        with self.lock:
            out = copy.deepcopy(self.data)
        gps, pos = out["gps"], out["position"]
        out.update(lat=gps["lat"], lon=gps["lon"], x=pos["x"], y=pos["y"],
                   sog=gps["sog"], cog=gps["cog"], kompas=gps["cog"])
        return out

    def pid_snapshot(self) -> dict:
        with self.lock:
            return dict(self.data["pid_config"])

    def set_live_frame(self, frame) -> None:
        with self.lock:
            self.live_frame_bgr = frame
            self._frame_sequence += 1

    def frame_snapshot(self):
        with self.lock:
            if self.live_frame_bgr is None:
                return None, self._frame_sequence
            return self.live_frame_bgr.copy(), self._frame_sequence

    def replace_mission(self, waypoints: list[dict]) -> None:
        with self.lock:
            self.data["mission"]["waypoints"] = waypoints
            self.data["mission"]["total"] = len(waypoints)
            self.data["timestamp"] = time.time()

    # ===== PERSISTENSI KONFIGURASI =====

    def save_config(self, path: Path) -> None:
        """Simpan hanya field konfigurasi ke file JSON dengan SHA."""
        with self.lock:
            config = {
                "pid_config": self.data.get("pid_config"),
                "currentTrack": self.data.get("currentTrack"),
                "home": self.data.get("home"),
                "loggerActive": self.data.get("loggerActive"),
            }
            # Simpan waypoints hanya jika ada isinya
            waypoints = self.data.get("mission", {}).get("waypoints", [])
            if waypoints:
                config["mission"] = {"waypoints": waypoints}

            # Buang nilai None
            config = {k: v for k, v in config.items() if v is not None}

            content = json.dumps(config, indent=2, ensure_ascii=False)
            sha = hashlib.sha256(content.encode()).hexdigest()
            path.write_text(content + f"\n# SHA256: {sha}", encoding="utf-8")

    def load_config(self, path: Path) -> None:
        """Muat konfigurasi dari file, verifikasi SHA."""
        if not path.exists():
            return
        raw = path.read_text(encoding="utf-8")
        # Pisahkan SHA jika ada
        if "# SHA256:" in raw:
            content, sha_line = raw.rsplit("# SHA256:", 1)
            content = content.strip()
            expected = sha_line.strip()
            actual = hashlib.sha256(content.encode()).hexdigest()
            if actual != expected:
                print("[STATE] SHA mismatch, konfigurasi diabaikan")
                return
        else:
            content = raw

        try:
            config = json.loads(content)
        except Exception as e:
            print(f"[STATE] Gagal parse state.json: {e}")
            return

        with self.lock:
            if "pid_config" in config:
                self.data["pid_config"].update(config["pid_config"])
            if "currentTrack" in config:
                self.data["currentTrack"] = config["currentTrack"]
            if "home" in config:
                self.data["home"] = config["home"]
            if "loggerActive" in config:
                self.data["loggerActive"] = config["loggerActive"]
            if "mission" in config and config["mission"].get("waypoints"):
                self.data["mission"]["waypoints"] = config["mission"]["waypoints"]
                self.data["mission"]["total"] = len(config["mission"]["waypoints"])


store = StateStore()