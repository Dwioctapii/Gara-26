"""Thread-safe shared ASV state."""
from __future__ import annotations
import copy, csv, json, os, threading, time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("ASV_DATA_DIR", ROOT / "data"))
PHOTO_DIR, LOG_DIR = DATA_DIR / "photos", DATA_DIR / "logs"
STATE_FILE = DATA_DIR / "state.json"

def defaults() -> dict[str, Any]:
    sensors = ("heartbeat", "eb", "pmb1", "pmb2", "manip", "thrusterPort", "thrusterStar", "ocs", "batPort", "batStar")
    return {
        "timestamp": time.time(), "connected": False,
        "position": {"x": 0., "y": 0., "z": 0.},
        "orientation": {"x": 0., "y": 0., "z": 0., "w": 1.},
        "linear": {"x": 0., "y": 0., "z": 0.}, "angular": {"x": 0., "y": 0., "z": 0.},
        "battery1": {"voltage": 0., "current": 0., "pressure": 0, "capacity": 0, "used": 0., "temp": 0},
        "thrusterPort": {"voltage": 0., "current": 0., "capacity": 0, "temp": 0},
        "thrusterStar": {"voltage": 0., "current": 0., "capacity": 0, "temp": 0},
        "gps": {"sog": 0., "cog": 0., "lat": None, "lon": None, "satellites": 0, "hdop": 99.9, "fix": False, "lastCalib": "-"},
        "speed": 0., "depth": 0., "sensors": {k: False for k in sensors},
        "mode": "Manual", "arm": "Disarmed", "missionState": "IDLE",
        "loggerActive": False, "currentTrack": "A", "mission": {"current": 0, "total": 0},
        "servo": [0, 0, 0, 0], "detection": {"red": [], "green": [], "gate": None, "angle": None},
        "home": None, "lastCommand": None, "lastError": None,
    }

def merge(dst: dict, src: dict) -> None:
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict): merge(dst[key], value)
        else: dst[key] = value

class StateStore:
    def __init__(self) -> None:
        for folder in (DATA_DIR, PHOTO_DIR, LOG_DIR): folder.mkdir(parents=True, exist_ok=True)
        self.lock, self.data, self.log_file = threading.RLock(), defaults(), None
        try:
            merge(self.data, json.loads(STATE_FILE.read_text("utf-8")))
            self.data.update(connected=False, loggerActive=False)
        except (OSError, json.JSONDecodeError): pass

    def snapshot(self) -> dict[str, Any]:
        with self.lock: out = copy.deepcopy(self.data)
        gps, pos = out["gps"], out["position"]
        out.update(lat=gps["lat"], lon=gps["lon"], x=pos["x"], y=pos["y"], sog=gps["sog"], cog=gps["cog"], kompas=gps["cog"])
        return out

    def update(self, patch: dict, persist: bool = False) -> None:
        with self.lock:
            merge(self.data, patch); self.data["timestamp"] = time.time()
            if self.data["loggerActive"]: self._log()
            if persist:
                tmp = STATE_FILE.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.data, indent=2), "utf-8"); tmp.replace(STATE_FILE)

    def command(self, cmd: dict) -> None:
        name, action, patch = cmd.get("command"), cmd.get("action"), {"lastCommand": cmd}
        if name == "set_mode" and cmd.get("mode") in {"Manual", "Auto", "Return Home"}: patch["mode"] = cmd["mode"]
        elif name == "arm" and action in {"arm", "disarm", "estop"}: patch["arm"] = {"arm":"Armed","disarm":"Disarmed","estop":"EStop"}[action]
        elif name == "mission" and action in {"start", "pause", "stop"}: patch["missionState"] = {"start":"RUNNING","pause":"PAUSED","stop":"STOPPED"}[action]
        elif name == "reset_mission": patch.update(missionState="IDLE", mission={"current": 0})
        elif name == "set_track" and cmd.get("track") in ("A", "B", "C", "D"): patch["currentTrack"] = cmd["track"]
        elif name == "go_home": patch.update(mode="Return Home", missionState="RETURNING HOME")
        elif name == "hold_position": patch["missionState"] = "HOLDING"
        elif name == "set_home": patch["home"] = {k:self.data["gps"][k] for k in ("lat","lon")}
        elif name == "calibration": patch["gps"] = {"lastCalib": time.strftime("%F %T")}
        elif name == "logger" and action in {"start", "stop"}:
            patch["loggerActive"] = action == "start"
            if action == "start": self.log_file = LOG_DIR / time.strftime("asv-%Y%m%d-%H%M%S.csv")
        self.update(patch, True)

    def _log(self) -> None:
        if self.log_file is None: self.log_file = LOG_DIR / time.strftime("asv-%Y%m%d-%H%M%S.csv")
        new = not self.log_file.exists(); gps, pos = self.data["gps"], self.data["position"]
        with self.log_file.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new: w.writerow(("timestamp","lat","lon","x","y","sog","cog","mode","arm","mission"))
            w.writerow((self.data["timestamp"],gps["lat"],gps["lon"],pos["x"],pos["y"],gps["sog"],gps["cog"],self.data["mode"],self.data["arm"],self.data["missionState"]))

store = StateStore()
def baca(): return store.snapshot()
def tulis(data): store.update(data, True)
