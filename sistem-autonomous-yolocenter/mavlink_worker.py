"""Pembaca MAVLink mandiri: telemetri + unduh mission Pixhawk berkala."""

import math
import threading
import time

from pymavlink import mavutil


class MavlinkWorker:
    def __init__(self, endpoint: str, baud: int, refresh_seconds: float, store) -> None:
        self.endpoint, self.baud, self.refresh_seconds, self.store = endpoint, baud, refresh_seconds, store
        self.master = None
        self.stop_event = threading.Event()
        self.last_request = 0.0
        self.downloading = False
        self.pending_total = 0
        self.pending_waypoints: list[dict] = []

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="mavlink").start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.master:
            self.master.close()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                print(f"[MAVLINK] Menghubungkan ke {self.endpoint}...")
                self.master = mavutil.mavlink_connection(self.endpoint, baud=self.baud)
                if self.master.wait_heartbeat(timeout=10) is None:
                    raise TimeoutError("heartbeat timeout")
                print(f"[MAVLINK] Terhubung ke system {self.master.target_system}")
                self.store.update({"connected": True, "lastError": None, "sensors": {"heartbeat": True}})
                self._request_mission()
                while not self.stop_event.is_set():
                    if time.monotonic() - self.last_request >= self.refresh_seconds and not self.downloading:
                        self._request_mission()
                    message = self.master.recv_match(blocking=True, timeout=0.2)
                    if message:
                        self._consume(message)
            except Exception as error:
                self.store.update({"connected": False, "lastError": f"MAVLink: {error}", "sensors": {"heartbeat": False}})
                if not self.stop_event.is_set():
                    time.sleep(2)

    def _request_mission(self) -> None:
        self.last_request, self.downloading = time.monotonic(), True
        try:
            self.master.mav.mission_request_list_send(self.master.target_system, self.master.target_component, mavutil.mavlink.MAV_MISSION_TYPE_MISSION)
        except TypeError:
            self.master.mav.mission_request_list_send(self.master.target_system, self.master.target_component)

    def _request_item(self, sequence: int) -> None:
        try:
            self.master.mav.mission_request_int_send(self.master.target_system, self.master.target_component, sequence, mavutil.mavlink.MAV_MISSION_TYPE_MISSION)
        except TypeError:
            self.master.mav.mission_request_int_send(self.master.target_system, self.master.target_component, sequence)

    def _consume(self, message) -> None:
        kind = message.get_type()
        if kind == "HEARTBEAT":
            # Filter hanya HEARTBEAT dari autopilot (komponen 1) agar status arm tidak tertimpa oleh komponen lain (misal radio)
            if message.get_srcComponent() == 1:
                armed = bool(message.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                self.store.update({"mode": (self.master.flightmode or "UNKNOWN").upper(), "arm": "Armed" if armed else "Disarmed"})
        elif kind == "ATTITUDE":
            self.store.update({"orientation": {"x": message.roll, "y": message.pitch, "z": message.yaw, "w": 1.0}, "angular": {"x": message.rollspeed, "y": message.pitchspeed, "z": message.yawspeed}})
        elif kind == "GLOBAL_POSITION_INT":
            speed = math.hypot(message.vx / 100.0, message.vy / 100.0)
            # Menghapus cog = message.hdg karena hdg adalah heading (kompas), bukan Course Over Ground
            self.store.update({"gps": {"lat": message.lat / 1e7, "lon": message.lon / 1e7, "fix": message.lat != 0 and message.lon != 0}, "linear": {"x": message.vx / 100.0, "y": message.vy / 100.0, "z": message.vz / 100.0}, "speed": speed, "position": {"z": message.relative_alt / 1000.0}})
        elif kind == "LOCAL_POSITION_NED":
            # UI ZIP memakai X=East, Y=North, Z=Up.
            self.store.update({"position": {"x": message.y, "y": message.x, "z": -message.z}})
        elif kind == "GPS_RAW_INT":
            hdop = 99.9 if message.eph == 65535 else message.eph / 100.0
            patch = {"satellites": message.satellites_visible, "hdop": hdop, "fix": message.fix_type >= 3}
            if message.vel != 65535:
                patch["sog"] = message.vel / 100.0
            if message.cog != 65535:
                patch["cog"] = message.cog / 100.0
            self.store.update({"gps": patch})
        elif kind == "SYS_STATUS":
            self.store.update({"battery1": {"voltage": max(0, message.voltage_battery) / 1000.0, "current": max(0, message.current_battery) / 100.0}})
        elif kind == "BATTERY_STATUS":
            cells = [v for v in message.voltages if v not in (0, 65535)]
            self.store.update({"battery1": {"voltage": sum(cells) / 1000.0, "current": max(0, message.current_battery) / 100.0, "used": max(0, message.current_consumed), "temp": 0 if message.temperature == 32767 else message.temperature / 100.0}})
        elif kind == "SERVO_OUTPUT_RAW":
            self.store.update({"servo": [message.servo1_raw, message.servo2_raw, message.servo3_raw, message.servo4_raw]})
        elif kind == "MISSION_CURRENT":
            total = getattr(message, "total", 0)
            patch = {"mission": {"current": message.seq}}
            # Beberapa autopilot/dialect lama tidak mengisi field total (0).
            # Jangan menimpa jumlah hasil MISSION_COUNT yang sudah valid.
            if total not in (0, 65535):
                patch["mission"]["total"] = total
            self.store.update(patch)
        elif kind == "MISSION_COUNT":
            self.pending_total, self.pending_waypoints = message.count, []
            if message.count:
                self._request_item(0)
            else:
                self.store.replace_mission([])
                self.downloading = False
        elif kind in ("MISSION_ITEM_INT", "MISSION_ITEM"):
            self._store_mission_item(message, kind == "MISSION_ITEM_INT")

    def handle_command(self, cmd: dict) -> dict:
        import os
        name, action = cmd.get("command"), cmd.get("action")
        hardware_command = name in {"arm", "set_mode", "go_home", "hold_position", "set_home"}
        hardware_command = hardware_command or (name == "mission" and action == "start")
        if not hardware_command:
            return {"sent": False, "reason": "state-only command"}

        enabled = os.getenv("ASV_ENABLE_COMMANDS", "0") == "1"
        if not enabled:
            return {"sent": False, "reason": "ASV_ENABLE_COMMANDS=0"}
        if self.master is None:
            raise RuntimeError("MAVLink belum terhubung")
        
        mapping = self.master.mode_mapping() or {}
        
        if name == "arm":
            if action == "estop":
                self.master.mav.command_long_send(self.master.target_system, self.master.target_component, mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 0, 21196, 0, 0, 0, 0, 0)
            elif action == "arm":
                self.master.arducopter_arm()
            else:
                self.master.arducopter_disarm()
        elif name in ("set_mode", "go_home", "hold_position"):
            mode = {"Manual": "MANUAL", "Auto": "AUTO", "Return Home": "RTL"}.get(cmd.get("mode")) if name == "set_mode" else ("RTL" if name == "go_home" else ("LOITER" if "LOITER" in mapping else "HOLD"))
            if mode not in mapping:
                raise ValueError(f"mode {mode} tidak tersedia")
            self.master.set_mode(mapping[mode])
        elif name == "mission" and action == "start":
            self.master.mav.command_long_send(self.master.target_system, self.master.target_component, mavutil.mavlink.MAV_CMD_MISSION_START, 0, 0, 0, 0, 0, 0, 0, 0)
        elif name == "set_home":
            self.master.mav.command_long_send(self.master.target_system, self.master.target_component, mavutil.mavlink.MAV_CMD_DO_SET_HOME, 0, 1, 0, 0, 0, 0, 0, 0)
        else:
            return {"sent": False, "reason": "state-only command"}
        return {"sent": True}

    def _store_mission_item(self, message, integer: bool) -> None:
        names = ("MAV_FRAME_GLOBAL", "MAV_FRAME_GLOBAL_RELATIVE_ALT", "MAV_FRAME_GLOBAL_TERRAIN_ALT", "MAV_FRAME_GLOBAL_INT", "MAV_FRAME_GLOBAL_RELATIVE_ALT_INT", "MAV_FRAME_GLOBAL_TERRAIN_ALT_INT")
        global_frames = {getattr(mavutil.mavlink, name) for name in names if hasattr(mavutil.mavlink, name)}
        is_global = message.frame in global_frames
        waypoint = {
            "seq": message.seq, "command": message.command, "frame": message.frame,
            "lat": message.x / 1e7 if integer and is_global else (message.x if is_global else None),
            "lon": message.y / 1e7 if integer and is_global else (message.y if is_global else None),
            "alt": message.z, "param1": message.param1, "param2": message.param2,
            "param3": message.param3, "param4": message.param4,
            "autocontinue": bool(message.autocontinue),
        }
        self.pending_waypoints = [item for item in self.pending_waypoints if item["seq"] != message.seq]
        self.pending_waypoints.append(waypoint)
        self.pending_waypoints.sort(key=lambda item: item["seq"])
        if message.seq + 1 < self.pending_total:
            self._request_item(message.seq + 1)
        else:
            self.store.replace_mission(self.pending_waypoints)
            self.downloading = False
            print(f"[MAVLINK] Mission tersinkron: {len(self.pending_waypoints)} item")
