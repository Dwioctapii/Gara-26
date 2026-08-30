import unittest

from pixel_distance import (
    average_valid_distances,
    bbox_width_pixels,
    estimate_camera_distance_m,
)


class PixelDistanceTests(unittest.TestCase):
    def test_35_cm_object_at_5_pixels_is_14_meters(self):
        bbox = [100.25, 20.0, 105.25, 40.0]
        distance = estimate_camera_distance_m(
            bbox,
            object_width_cm=35.0,
            focal_length_px=200.0,
        )

        self.assertAlmostEqual(distance, 14.0)

    def test_bbox_width_keeps_decimal_precision(self):
        self.assertAlmostEqual(
            bbox_width_pixels([10.25, 0.0, 15.75, 20.0]),
            5.5,
        )

    def test_larger_bbox_means_closer_object(self):
        close = estimate_camera_distance_m([0, 0, 20, 10], 35.0, 200.0)
        far = estimate_camera_distance_m([0, 0, 5, 10], 35.0, 200.0)

        self.assertLess(close, far)

    def test_invalid_bbox_returns_none(self):
        self.assertIsNone(
            estimate_camera_distance_m([10, 0, 10, 20], 35.0, 200.0)
        )

    def test_midpoint_average_ignores_invalid_distance(self):
        self.assertAlmostEqual(average_valid_distances(4.0, 6.0), 5.0)
        self.assertAlmostEqual(average_valid_distances(None, 6.0), 6.0)
        self.assertIsNone(average_valid_distances(None, None))


if __name__ == "__main__":
    unittest.main()
