"""State thread-safe untuk telemetri, target YOLO, dan status kontrol."""

from __future__ import annotations

import copy
import threading
import time

from models import TargetObservation, parse_yolo_target


def _merge(target: dict, patch: dict) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value


class StateStore:
    def __init__(self, auto_start: bool = False) -> None:
        self.lock = threading.RLock()
        self._target: TargetObservation | None = None
        self._target_monotonic = 0.0
        self.data = {
            "timestamp": time.time(),
            "connected": False,
            "lastError": None,
            "mode": "DISCONNECTED",
            "arm": "Disarmed",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "orientation": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
            "linear": {"x": 0.0, "y": 0.0, "z": 0.0},
            "angular": {"x": 0.0, "y": 0.0, "z": 0.0},
            "gps": {
                "lat": None,
                "lon": None,
                "sog": 0.0,
                "cog": 0.0,
                "satellites": 0,
                "hdop": 99.9,
                "fix": False,
            },
            "battery": {"voltage": 0.0, "current": 0.0},
            "mission": {"current": 0, "total": 0, "waypoints": []},
            "vision": {
                "connected": False,
                "last_error": None,
                "received_at": None,
                "target": None,
                "target_age_seconds": None,
                "target_pair_id": None,
                "focus_side": None,
                "pair_count": 0,
                "buoy_count": 0,
            },
            "autonomy": {
                "enabled": auto_start,
                "status": "DISABLED" if not auto_start else "STARTING",
                "forward_mps": 0.0,
                "yaw_rate_rps": 0.0,
                "updated_at": time.time(),
            },
            "lastCommand": None,
        }

    def update(self, patch: dict) -> None:
        with self.lock:
            _merge(self.data, patch)
            self.data["timestamp"] = time.time()

    def ingest_yolo(self, payload: dict) -> TargetObservation | None:
        target = parse_yolo_target(payload)
        now_wall = time.time()
        now_monotonic = time.monotonic()
        with self.lock:
            self._target = target
            self._target_monotonic = now_monotonic
            target_json = None
            if target is not None:
                target_json = {
                    "pair_id": target.pair_id,
                    "bearing_degrees": target.bearing_degrees,
                    "distance_m": target.distance_m,
                    "midpoint_x": target.midpoint_x,
                    "confidence": target.confidence,
                }
            self.data["vision"].update(
                connected=True,
                last_error=None,
                received_at=now_wall,
                target=target_json,
                target_age_seconds=0.0,
                target_pair_id=target.pair_id if target else None,
                focus_side=payload.get("focus_side"),
                pair_count=len(payload.get("pairs", [])),
                buoy_count=len(payload.get("buoys", [])),
            )
            self.data["timestamp"] = now_wall
        return target

    def set_vision_error(self, message: str) -> None:
        self.update({"vision": {"last_error": message}})

    def latest_target(self) -> tuple[TargetObservation | None, float]:
        with self.lock:
            target = self._target
            received = self._target_monotonic
        age = float("inf") if received == 0.0 else time.monotonic() - received
        return target, age

    def control_snapshot(self) -> dict:
        with self.lock:
            return {
                "enabled": bool(self.data["autonomy"]["enabled"]),
                "mavlink_connected": bool(self.data["connected"]),
                "armed": self.data["arm"] == "Armed",
                "mode": str(self.data["mode"]).upper(),
            }

    def update_control(
        self,
        status: str,
        forward_mps: float,
        yaw_rate_rps: float,
    ) -> None:
        self.update(
            {
                "autonomy": {
                    "status": status,
                    "forward_mps": round(forward_mps, 4),
                    "yaw_rate_rps": round(yaw_rate_rps, 4),
                    "updated_at": time.time(),
                }
            }
        )

    def command(self, cmd: dict) -> dict:
        name = cmd.get("command")
        action = cmd.get("action")
        patch = {"lastCommand": cmd}
        if name == "autonomy" and action in {"enable", "disable"}:
            enabled = action == "enable"
            patch["autonomy"] = {
                "enabled": enabled,
                "status": "STARTING" if enabled else "DISABLED",
            }
        self.update(patch)
        return {"state_updated": True}

    def snapshot(self) -> dict:
        with self.lock:
            out = copy.deepcopy(self.data)
            received = self._target_monotonic
        if received:
            out["vision"]["target_age_seconds"] = round(
                time.monotonic() - received,
                3,
            )
        gps = out["gps"]
        out.update(
            lat=gps["lat"],
            lon=gps["lon"],
            sog=gps["sog"],
            cog=gps["cog"],
            kompas=gps["cog"],
        )
        return out


store = StateStore()
