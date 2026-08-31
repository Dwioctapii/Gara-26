import unittest

from models import parse_yolo_target


class TargetParserTests(unittest.TestCase):
    def test_uses_explicit_target_pair(self):
        payload = {
            "target_pair_id": 2,
            "pairs": [
                {"id": 1, "distance": 1.0, "bearing_degrees": -20.0},
                {
                    "id": 2,
                    "distance": 8.5,
                    "bearing_degrees": 12.0,
                    "midpoint_x": 0.25,
                },
            ],
            "buoys": [
                {"pair_id": 2, "confidence": 0.91},
                {"pair_id": 2, "confidence": 0.87},
            ],
        }

        target = parse_yolo_target(payload)

        self.assertEqual(target.pair_id, 2)
        self.assertEqual(target.distance_m, 8.5)
        self.assertEqual(target.bearing_degrees, 12.0)
        self.assertEqual(target.confidence, 0.87)

    def test_empty_target_clears_tracking(self):
        self.assertIsNone(
            parse_yolo_target({"target_pair_id": None, "pairs": [], "buoys": []})
        )

    def test_missing_target_pair_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_yolo_target({"target_pair_id": 9, "pairs": []})

    def test_invalid_distance_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_yolo_target(
                {
                    "target_pair_id": 1,
                    "pairs": [
                        {"id": 1, "distance": None, "bearing_degrees": 0}
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()

