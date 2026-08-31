"""Pengubah bearing/jarak target menjadi setpoint gerak kapal."""

from __future__ import annotations

from dataclasses import dataclass
import math
import threading
import time

from models import TargetObservation


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


@dataclass(frozen=True)
class MotionCommand:
    forward_mps: float
    yaw_rate_rps: float
    status: str


@dataclass(frozen=True)
class ControlTuning:
    stop_distance_m: float = 2.0
    distance_kp: float = 0.45
    max_forward_mps: float = 1.5
    heading_kp: float = 1.2
    max_yaw_rate_rps: float = 0.7
    bearing_deadband_degrees: float = 2.0
    drive_bearing_limit_degrees: float = 55.0


def calculate_motion(
    target: TargetObservation,
    tuning: ControlTuning,
) -> MotionCommand:
    """Kontrol proporsional yang mudah diuji dan dituning di lapangan."""

    if target.distance_m <= tuning.stop_distance_m:
        return MotionCommand(0.0, 0.0, "AT_TARGET")

    bearing_radians = math.radians(target.bearing_degrees)
    yaw_rate = 0.0
    if abs(target.bearing_degrees) > tuning.bearing_deadband_degrees:
        yaw_rate = clamp(
            tuning.heading_kp * bearing_radians,
            -tuning.max_yaw_rate_rps,
            tuning.max_yaw_rate_rps,
        )

    distance_error = target.distance_m - tuning.stop_distance_m
    forward = clamp(
        tuning.distance_kp * distance_error,
        0.0,
        tuning.max_forward_mps,
    )

    # Kurangi maju saat target menyamping; di luar batas, putar di tempat.
    absolute_bearing = abs(target.bearing_degrees)
    if absolute_bearing >= tuning.drive_bearing_limit_degrees:
        forward = 0.0
    else:
        forward *= max(0.0, math.cos(bearing_radians))

    return MotionCommand(forward, yaw_rate, "TRACKING")


class AutonomyController:
    def __init__(self, config, store, mavlink) -> None:
        self.config = config
        self.store = store
        self.mavlink = mavlink
        self.stop_event = threading.Event()
        self.tuning = ControlTuning(
            stop_distance_m=config.STOP_DISTANCE_M,
            distance_kp=config.DISTANCE_KP,
            max_forward_mps=config.MAX_FORWARD_MPS,
            heading_kp=config.HEADING_KP,
            max_yaw_rate_rps=config.MAX_YAW_RATE_RPS,
            bearing_deadband_degrees=config.BEARING_DEADBAND_DEGREES,
            drive_bearing_limit_degrees=config.DRIVE_BEARING_LIMIT_DEGREES,
        )
        self._was_enabled = False

    def start(self) -> None:
        threading.Thread(
            target=self._run,
            daemon=True,
            name="autonomy-control",
        ).start()

    def stop(self) -> None:
        self.stop_event.set()
        if self._was_enabled:
            try:
                self._send(0.0, 0.0, "SHUTDOWN")
            except Exception as exc:
                self.store.update(
                    {"lastError": f"Gagal mengirim stop saat shutdown: {exc}"}
                )

    def _send(self, forward: float, yaw_rate: float, status: str) -> None:
        self.mavlink.send_movement(forward, yaw_rate)
        self.store.update_control(status, forward, yaw_rate)

    def _run(self) -> None:
        interval = 1.0 / max(self.config.CONTROL_HZ, 1.0)
        while not self.stop_event.is_set():
            loop_started = time.monotonic()
            try:
                snapshot = self.store.control_snapshot()
                enabled = snapshot["enabled"]

                if not enabled:
                    # Kirim nol sekali saat transisi ON -> OFF jika mode masih
                    # menerima kontrol. Bila mode/link sudah berubah, catat
                    # DISABLED dan andalkan timeout setpoint autopilot.
                    can_send_stop = snapshot["mavlink_connected"] and (
                        self.config.MAVLINK_CONTROL_MODE == "manual"
                        or snapshot["mode"] == self.config.MAVLINK_REQUIRED_MODE
                    )
                    if self._was_enabled and can_send_stop:
                        try:
                            self._send(0.0, 0.0, "DISABLED")
                        except Exception as exc:
                            self.store.update(
                                {"lastError": f"Gagal mengirim stop: {exc}"}
                            )
                            self.store.update_control("DISABLED", 0.0, 0.0)
                    else:
                        self.store.update_control("DISABLED", 0.0, 0.0)
                    self._was_enabled = False
                elif not snapshot["mavlink_connected"]:
                    self.store.update_control("WAITING_FOR_MAVLINK", 0.0, 0.0)
                    self._was_enabled = True
                elif (
                    self.config.MAVLINK_CONTROL_MODE == "velocity"
                    and snapshot["mode"] != self.config.MAVLINK_REQUIRED_MODE
                ):
                    # ArduRover mengabaikan SET_POSITION_TARGET_LOCAL_NED jika
                    # kendaraan tidak berada pada mode kontrol eksternal.
                    # Jangan melaporkan TRACKING sebelum HEARTBEAT benar-benar
                    # mengonfirmasi mode yang diminta.
                    if self.config.AUTO_SET_GUIDED:
                        self.mavlink.request_control_mode()
                    self.store.update_control(
                        f"WAITING_FOR_{self.config.MAVLINK_REQUIRED_MODE}",
                        0.0,
                        0.0,
                    )
                    self._was_enabled = True
                elif self.config.REQUIRE_ARMED and not snapshot["armed"]:
                    self._send(0.0, 0.0, "WAITING_FOR_ARM")
                    self._was_enabled = True
                else:
                    self._was_enabled = True
                    target, age = self.store.latest_target()
                    if target is None or age > self.config.TARGET_TIMEOUT_SECONDS:
                        self._send(0.0, 0.0, "TARGET_LOST")
                    else:
                        command = calculate_motion(target, self.tuning)
                        self._send(
                            command.forward_mps,
                            command.yaw_rate_rps,
                            command.status,
                        )
            except Exception as exc:
                # Gangguan sesaat pada serial/UDP tidak boleh membunuh thread
                # keselamatan. Loop tetap hidup dan mencoba lagi pada tick lalu.
                self.store.update(
                    {
                        "lastError": f"Autonomy control: {exc}",
                        "autonomy": {
                            "status": "CONTROL_ERROR",
                            "forward_mps": 0.0,
                            "yaw_rate_rps": 0.0,
                            "updated_at": time.time(),
                        },
                    }
                )

            elapsed = time.monotonic() - loop_started
            self.stop_event.wait(max(0.0, interval - elapsed))
