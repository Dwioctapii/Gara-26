"""Koneksi MAVLink: telemetri, perintah operator, dan setpoint gerak."""

from __future__ import annotations

import math
import threading
import time

from pymavlink import mavutil


class MavlinkWorker:
    def __init__(self, config, store) -> None:
        self.config = config
        self.store = store
        self.master = None
        self.stop_event = threading.Event()
        self.send_lock = threading.Lock()
        self._last_vehicle_heartbeat = 0.0
        self._last_companion_heartbeat = 0.0
        self._last_mode_request = 0.0

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="mavlink").start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.master:
            try:
                self.master.close()
            except Exception:
                pass

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                print(f"[MAVLINK] Menghubungkan ke {self.config.MAVLINK_ENDPOINT}...")
                self.master = mavutil.mavlink_connection(
                    self.config.MAVLINK_ENDPOINT,
                    baud=self.config.MAVLINK_BAUD,
                )
                if self.master.wait_heartbeat(timeout=10) is None:
                    raise TimeoutError("heartbeat timeout")
                self._last_vehicle_heartbeat = time.monotonic()
                self.store.update(
                    {"connected": True, "lastError": None}
                )
                print(
                    f"[MAVLINK] Terhubung ke system {self.master.target_system}"
                )
                while not self.stop_event.is_set():
                    self._send_companion_heartbeat_if_due()
                    message = self.master.recv_match(blocking=True, timeout=0.2)
                    if message:
                        self._consume(message)
                    if (
                        time.monotonic() - self._last_vehicle_heartbeat
                        > self.config.MAVLINK_HEARTBEAT_TIMEOUT_SECONDS
                    ):
                        raise TimeoutError("heartbeat kendaraan terputus")
            except Exception as error:
                stale_master = self.master
                self.master = None
                print(f"[MAVLINK] Gagal: {error}; mencoba lagi dalam 2 detik")
                self.store.update(
                    {"connected": False, "lastError": f"MAVLink: {error}"}
                )
                if stale_master:
                    try:
                        stale_master.close()
                    except Exception:
                        pass
                if not self.stop_event.is_set():
                    time.sleep(2.0)

    def _send_companion_heartbeat_if_due(self) -> None:
        interval = 1.0 / max(self.config.MAVLINK_HEARTBEAT_HZ, 0.1)
        now = time.monotonic()
        if now - self._last_companion_heartbeat < interval:
            return
        mav_type = getattr(
            mavutil.mavlink,
            "MAV_TYPE_ONBOARD_CONTROLLER",
            mavutil.mavlink.MAV_TYPE_GCS,
        )
        with self.send_lock:
            self.master.mav.heartbeat_send(
                mav_type,
                mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                0,
                0,
                mavutil.mavlink.MAV_STATE_ACTIVE,
            )
        self._last_companion_heartbeat = now

    def _consume(self, message) -> None:
        kind = message.get_type()
        if kind == "HEARTBEAT" and message.get_srcComponent() == 1:
            self._last_vehicle_heartbeat = time.monotonic()
            armed = bool(
                message.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
            )
            self.store.update(
                {
                    "mode": (self.master.flightmode or "UNKNOWN").upper(),
                    "arm": "Armed" if armed else "Disarmed",
                }
            )
        elif kind == "ATTITUDE":
            self.store.update(
                {
                    "orientation": {
                        "roll": message.roll,
                        "pitch": message.pitch,
                        "yaw": message.yaw,
                    },
                    "angular": {
                        "x": message.rollspeed,
                        "y": message.pitchspeed,
                        "z": message.yawspeed,
                    },
                }
            )
        elif kind == "GLOBAL_POSITION_INT":
            self.store.update(
                {
                    "gps": {
                        "lat": message.lat / 1e7,
                        "lon": message.lon / 1e7,
                        "fix": message.lat != 0 and message.lon != 0,
                    },
                    "linear": {
                        "x": message.vx / 100.0,
                        "y": message.vy / 100.0,
                        "z": message.vz / 100.0,
                    },
                    "position": {"z": message.relative_alt / 1000.0},
                }
            )
        elif kind == "LOCAL_POSITION_NED":
            self.store.update(
                {"position": {"x": message.y, "y": message.x, "z": -message.z}}
            )
        elif kind == "GPS_RAW_INT":
            patch = {
                "satellites": message.satellites_visible,
                "hdop": 99.9 if message.eph == 65535 else message.eph / 100.0,
                "fix": message.fix_type >= 3,
            }
            if message.vel != 65535:
                patch["sog"] = message.vel / 100.0
            if message.cog != 65535:
                patch["cog"] = message.cog / 100.0
            self.store.update({"gps": patch})
        elif kind == "SYS_STATUS":
            self.store.update(
                {
                    "battery": {
                        "voltage": max(0, message.voltage_battery) / 1000.0,
                        "current": max(0, message.current_battery) / 100.0,
                    }
                }
            )
        elif kind == "MISSION_CURRENT":
            self.store.update({"mission": {"current": message.seq}})

    def request_control_mode(self) -> bool:
        """Minta mode kontrol dan tunggu HEARTBEAT sebagai konfirmasi.

        Return True hanya bila flight mode yang dibaca dari autopilot sudah
        sama. Request dibatasi satu kali per detik agar tidak membanjiri link.
        """

        if self.master is None:
            return False
        current = str(self.master.flightmode or "UNKNOWN").upper()
        required = self.config.MAVLINK_REQUIRED_MODE
        if current == required:
            return True
        if not self.config.AUTO_SET_GUIDED:
            return False
        now = time.monotonic()
        if now - self._last_mode_request < 1.0:
            return False
        mapping = self.master.mode_mapping() or {}
        if required not in mapping:
            raise RuntimeError(f"mode {required} tidak tersedia di autopilot")
        with self.send_lock:
            self.master.set_mode(mapping[required])
        self._last_mode_request = now
        return False

    def send_movement(self, forward_mps: float, yaw_rate_rps: float) -> None:
        if self.master is None:
            raise RuntimeError("MAVLink belum terhubung")
        with self.send_lock:
            if self.config.MAVLINK_CONTROL_MODE == "manual":
                self._send_manual(forward_mps, yaw_rate_rps)
            else:
                current = str(self.master.flightmode or "UNKNOWN").upper()
                if current != self.config.MAVLINK_REQUIRED_MODE:
                    raise RuntimeError(
                        f"mode {current}; perlu {self.config.MAVLINK_REQUIRED_MODE}"
                    )
                self._send_body_velocity(forward_mps, yaw_rate_rps)

    def _send_body_velocity(self, forward_mps: float, yaw_rate_rps: float) -> None:
        # ArduRover: gunakan vx dan yaw_rate. Posisi, vz, akselerasi, dan yaw
        # diabaikan. Mask 1511 mengikuti contoh resmi Rover untuk velocity XY
        # + yaw-rate; BODY_OFFSET_NED membuat vx relatif terhadap haluan kapal.
        type_mask = (
            (1 << 0)
            | (1 << 1)
            | (1 << 2)
            | (1 << 5)
            | (1 << 6)
            | (1 << 7)
            | (1 << 8)
            | (1 << 10)
        )
        self.master.mav.set_position_target_local_ned_send(
            int(time.monotonic() * 1000) & 0xFFFFFFFF,
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED,
            type_mask,
            0.0,
            0.0,
            0.0,
            float(forward_mps),
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            float(yaw_rate_rps),
        )

    def _send_manual(self, forward_mps: float, yaw_rate_rps: float) -> None:
        throttle = int(
            max(0.0, min(1.0, forward_mps / self.config.MAX_FORWARD_MPS))
            * 1000
        )
        turn = int(
            max(-1.0, min(1.0, yaw_rate_rps / self.config.MAX_YAW_RATE_RPS))
            * 1000
        )
        # MANUAL_CONTROL: x/y/r -1000..1000, z throttle 0..1000.
        self.master.mav.manual_control_send(
            self.master.target_system,
            0,
            0,
            throttle,
            turn,
            0,
        )

    def handle_command(self, cmd: dict) -> dict:
        if cmd.get("command") == "autonomy":
            return {"sent": False, "reason": "state-only command"}
        if not self.config.ENABLE_REMOTE_MAVLINK_COMMANDS:
            return {"sent": False, "reason": "NEO_ENABLE_REMOTE_COMMANDS=0"}
        if self.master is None:
            raise RuntimeError("MAVLink belum terhubung")

        name, action = cmd.get("command"), cmd.get("action")
        if name == "arm":
            with self.send_lock:
                if action == "arm":
                    # Nama helper berasal dari pymavlink tetapi command yang
                    # dikirim juga berlaku untuk ArduRover.
                    self.master.arducopter_arm()
                elif action == "disarm":
                    self.master.arducopter_disarm()
                else:
                    raise ValueError("action arm harus arm atau disarm")
        elif name == "set_mode":
            mode = str(cmd.get("mode", "")).upper()
            mapping = self.master.mode_mapping() or {}
            if mode not in mapping:
                raise ValueError(f"mode {mode} tidak tersedia")
            with self.send_lock:
                self.master.set_mode(mapping[mode])
        else:
            return {"sent": False, "reason": "command tidak dikenali"}
        return {"sent": True}
