import sys
import types
import unittest


try:
    from pymavlink import mavutil  # noqa: F401
except ModuleNotFoundError:
    fake_constants = types.SimpleNamespace(
        MAV_FRAME_BODY_OFFSET_NED=9,
        MAV_MODE_FLAG_SAFETY_ARMED=128,
        MAV_TYPE_GCS=6,
        MAV_TYPE_ONBOARD_CONTROLLER=18,
        MAV_AUTOPILOT_INVALID=8,
        MAV_STATE_ACTIVE=4,
    )
    fake_mavutil = types.SimpleNamespace(mavlink=fake_constants)
    fake_package = types.ModuleType("pymavlink")
    fake_package.mavutil = fake_mavutil
    sys.modules["pymavlink"] = fake_package

from mavlink_worker import MavlinkWorker


class FakeMav:
    def __init__(self):
        self.position_targets = []

    def set_position_target_local_ned_send(self, *args):
        self.position_targets.append(args)


class FakeMaster:
    def __init__(self, flightmode="GUIDED"):
        self.flightmode = flightmode
        self.target_system = 1
        self.target_component = 1
        self.mav = FakeMav()
        self.mode_requests = []

    def mode_mapping(self):
        return {"GUIDED": 15, "MANUAL": 0}

    def set_mode(self, mode):
        self.mode_requests.append(mode)


class FakeStore:
    def update(self, _patch):
        pass


class Config:
    MAVLINK_CONTROL_MODE = "velocity"
    MAVLINK_REQUIRED_MODE = "GUIDED"
    AUTO_SET_GUIDED = True
    MAX_FORWARD_MPS = 1.5
    MAX_YAW_RATE_RPS = 0.7


class MavlinkMovementTests(unittest.TestCase):
    def worker(self, flightmode="GUIDED"):
        worker = MavlinkWorker(Config, FakeStore())
        worker.master = FakeMaster(flightmode)
        return worker

    def test_body_velocity_uses_rover_frame_and_mask(self):
        worker = self.worker()

        worker.send_movement(1.25, -0.3)

        message = worker.master.mav.position_targets[-1]
        self.assertEqual(message[3], 9)
        self.assertEqual(message[4], 1511)
        self.assertEqual(message[8], 1.25)
        self.assertEqual(message[9], 0.0)
        self.assertEqual(message[10], 0.0)
        self.assertEqual(message[15], -0.3)

    def test_velocity_is_rejected_outside_guided(self):
        worker = self.worker("MANUAL")

        with self.assertRaisesRegex(RuntimeError, "perlu GUIDED"):
            worker.send_movement(0.5, 0.0)

    def test_mode_request_waits_for_heartbeat_confirmation(self):
        worker = self.worker("MANUAL")

        self.assertFalse(worker.request_control_mode())
        self.assertEqual(worker.master.mode_requests, [15])

        worker.master.flightmode = "GUIDED"
        self.assertTrue(worker.request_control_mode())


if __name__ == "__main__":
    unittest.main()
