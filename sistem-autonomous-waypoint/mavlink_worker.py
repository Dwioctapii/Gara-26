"""Telemetri MAVLink dan sinkronisasi mission Pixhawk yang atomik."""
import math
import threading
import time
from pymavlink import mavutil


class MavlinkWorker:
    def __init__(self, endpoint, baud, refresh_seconds, store, item_timeout=1.0,
                 max_retries=4, reached_radius=1.5):
        self.endpoint, self.baud = endpoint, baud
        self.refresh_seconds, self.store = max(2.0, refresh_seconds), store
        self.item_timeout, self.max_retries, self.reached_radius = item_timeout, max_retries, reached_radius
        self.master = None
        self.stop_event = threading.Event()
        self.last_request = 0.0
        self.downloading = False
        self.pending_total, self.pending = 0, {}
        self.requested_seq, self.request_deadline, self.retries = None, 0.0, 0

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="mavlink").start()

    def stop(self):
        self.stop_event.set()
        if self.master:
            self.master.close()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                print(f"[MAVLINK] Menghubungkan ke {self.endpoint}...")
                self.master = mavutil.mavlink_connection(self.endpoint, baud=self.baud)
                if self.master.wait_heartbeat(timeout=10) is None:
                    raise TimeoutError("heartbeat timeout")
                self.store.update({"connected": True, "lastError": None,
                                   "sensors": {"heartbeat": True}})
                self._request_mission()
                while not self.stop_event.is_set():
                    now = time.monotonic()
                    if self.downloading and now >= self.request_deadline:
                        self._retry_or_abort()
                    elif not self.downloading and now - self.last_request >= self.refresh_seconds:
                        self._request_mission()
                    message = self.master.recv_match(blocking=True, timeout=0.15)
                    if message:
                        self._consume(message)
            except Exception as error:
                self.downloading = False
                self.store.set_mission_syncing(False)
                self.store.update({"connected": False, "lastError": f"MAVLink: {error}",
                                   "sensors": {"heartbeat": False}})
                if not self.stop_event.is_set():
                    time.sleep(2)

    def _send(self, method, *args):
        try:
            method(*args, mavutil.mavlink.MAV_MISSION_TYPE_MISSION)
        except TypeError:
            method(*args)

    def _request_mission(self):
        self.last_request = time.monotonic()
        self.downloading, self.pending_total, self.pending = True, 0, {}
        self.requested_seq, self.retries = None, 0
        self.request_deadline = self.last_request + self.item_timeout
        self.store.set_mission_syncing(True)
        self._send(self.master.mav.mission_request_list_send,
                   self.master.target_system, self.master.target_component)

    def _request_item(self, seq):
        self.requested_seq = seq
        self.request_deadline = time.monotonic() + self.item_timeout
        self._send(self.master.mav.mission_request_int_send,
                   self.master.target_system, self.master.target_component, seq)

    def _next_missing(self):
        return next((seq for seq in range(self.pending_total) if seq not in self.pending), None)

    def _retry_or_abort(self):
        if self.retries >= self.max_retries:
            self.downloading = False
            self.store.set_mission_syncing(False)
            self.store.update({"lastError": "Mission sync timeout; daftar lama dipertahankan"})
            return
        self.retries += 1
        if self.pending_total:
            seq = self.requested_seq if self.requested_seq not in self.pending else self._next_missing()
            self._request_item(seq)
        else:
            self.request_deadline = time.monotonic() + self.item_timeout
            self._send(self.master.mav.mission_request_list_send,
                       self.master.target_system, self.master.target_component)

    def _consume(self, message):
        kind = message.get_type()
        if kind == "HEARTBEAT":
            armed = bool(message.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            self.store.update({"mode": (self.master.flightmode or "UNKNOWN").upper(),
                               "arm": "Armed" if armed else "Disarmed"})
        elif kind == "ATTITUDE":
            self.store.update({"orientation": {"x": message.roll, "y": message.pitch, "z": message.yaw, "w": 1.0},
                               "angular": {"x": message.rollspeed, "y": message.pitchspeed, "z": message.yawspeed},
                               "sensors": {"imu": True}})
        elif kind == "GLOBAL_POSITION_INT":
            speed = math.hypot(message.vx, message.vy) / 100.0
            cog = 0.0 if message.hdg == 65535 else message.hdg / 100.0
            valid = message.lat != 0 and message.lon != 0
            self.store.update({"gps": {"lat": message.lat / 1e7, "lon": message.lon / 1e7,
                                       "sog": speed, "cog": cog, "fix": valid},
                               "linear": {"x": message.vx / 100.0, "y": message.vy / 100.0, "z": message.vz / 100.0},
                               "speed": speed, "position": {"z": message.relative_alt / 1000.0},
                               "sensors": {"gps": valid}})
            self.store.refresh_navigation()
        elif kind == "LOCAL_POSITION_NED":
            self.store.update({"position": {"x": message.y, "y": message.x, "z": -message.z}})
        elif kind == "GPS_RAW_INT":
            hdop = 99.9 if message.eph == 65535 else message.eph / 100.0
            self.store.update({"gps": {"satellites": message.satellites_visible,
                                       "hdop": hdop, "fix": message.fix_type >= 3}})
        elif kind == "SYS_STATUS":
            self.store.update({"battery1": {"voltage": message.voltage_battery / 1000.0,
                                             "current": max(0.0, message.current_battery / 100.0),
                                             "percentage": max(0, message.battery_remaining)}})
        elif kind == "MISSION_CURRENT":
            patch = {"mission": {"current": int(message.seq)}}
            total = int(getattr(message, "total", 0))
            if total not in (0, 65535):
                patch["mission"]["total"] = total
            self.store.update(patch)
            self.store.refresh_navigation()
        elif kind == "MISSION_COUNT" and self.downloading:
            self.pending_total, self.pending, self.retries = int(message.count), {}, 0
            if self.pending_total == 0:
                self.store.replace_mission([])
                self.downloading = False
            else:
                self._request_item(0)
        elif kind in ("MISSION_ITEM_INT", "MISSION_ITEM") and self.downloading:
            self._store_mission_item(message, kind == "MISSION_ITEM_INT")

    def _store_mission_item(self, message, integer):
        global_frames = {getattr(mavutil.mavlink, name) for name in (
            "MAV_FRAME_GLOBAL", "MAV_FRAME_GLOBAL_RELATIVE_ALT", "MAV_FRAME_GLOBAL_TERRAIN_ALT",
            "MAV_FRAME_GLOBAL_INT", "MAV_FRAME_GLOBAL_RELATIVE_ALT_INT",
            "MAV_FRAME_GLOBAL_TERRAIN_ALT_INT") if hasattr(mavutil.mavlink, name)}
        is_global = message.frame in global_frames
        self.pending[int(message.seq)] = {
            "seq": int(message.seq), "command": int(message.command), "frame": int(message.frame),
            "lat": message.x / 1e7 if integer and is_global else (float(message.x) if is_global else None),
            "lon": message.y / 1e7 if integer and is_global else (float(message.y) if is_global else None),
            "x": None if is_global else float(message.x), "y": None if is_global else float(message.y),
            "alt": float(message.z), "param1": float(message.param1), "param2": float(message.param2),
            "param3": float(message.param3), "param4": float(message.param4),
            "acceptanceRadius": float(message.param2) if message.param2 > 0 else self.reached_radius,
            "autocontinue": bool(message.autocontinue)}
        self.retries = 0
        missing = self._next_missing()
        if missing is None:
            self.store.replace_mission([self.pending[i] for i in range(self.pending_total)])
            self.downloading = False
            self.last_request = time.monotonic()
            print(f"[MAVLINK] Mission tersinkron: {self.pending_total} item")
        else:
            self._request_item(missing)
