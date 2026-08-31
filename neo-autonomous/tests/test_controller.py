import unittest

from controller import ControlTuning, calculate_motion
from models import TargetObservation


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tuning = ControlTuning(
            stop_distance_m=2.0,
            distance_kp=0.5,
            max_forward_mps=1.5,
            heading_kp=1.0,
            max_yaw_rate_rps=0.6,
            bearing_deadband_degrees=2.0,
            drive_bearing_limit_degrees=55.0,
        )

    def target(self, distance, bearing):
        return TargetObservation(1, bearing, distance)

    def test_stops_at_target_distance(self):
        command = calculate_motion(self.target(1.9, 20), self.tuning)
        self.assertEqual(command.forward_mps, 0.0)
        self.assertEqual(command.yaw_rate_rps, 0.0)
        self.assertEqual(command.status, "AT_TARGET")

    def test_positive_bearing_turns_right(self):
        command = calculate_motion(self.target(8.0, 15.0), self.tuning)
        self.assertGreater(command.forward_mps, 0.0)
        self.assertGreater(command.yaw_rate_rps, 0.0)

    def test_negative_bearing_turns_left(self):
        command = calculate_motion(self.target(8.0, -15.0), self.tuning)
        self.assertLess(command.yaw_rate_rps, 0.0)

    def test_large_bearing_rotates_without_forward_motion(self):
        command = calculate_motion(self.target(8.0, 70.0), self.tuning)
        self.assertEqual(command.forward_mps, 0.0)
        self.assertEqual(command.yaw_rate_rps, 0.6)

    def test_deadband_keeps_yaw_zero(self):
        command = calculate_motion(self.target(8.0, 1.5), self.tuning)
        self.assertEqual(command.yaw_rate_rps, 0.0)


if __name__ == "__main__":
    unittest.main()

