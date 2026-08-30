import unittest

from buoy_pairing import (
    buoy_color,
    frontmost_pair,
    pair_buoys,
)


def detection(class_name, box, score=0.9):
    return {"class_name": class_name, "box": box, "score": score}


class BuoyPairingTests(unittest.TestCase):
    def test_decimal_pixel_distance_midpoint_and_range(self):
        detections = [
            detection("buoygreen", [90.25, 180.0, 110.75, 220.0]),
            detection("buoyred", [290.50, 180.0, 311.00, 220.0]),
        ]

        pairs = pair_buoys(
            detections,
            frame_width=640,
            frame_height=480,
            known_pair_width_m=2.0,
            horizontal_fov_degrees=90.0,
        )

        self.assertEqual(len(pairs), 1)
        pair = pairs[0]
        self.assertAlmostEqual(pair["pixel_distance"], 200.25)
        self.assertAlmostEqual(pair["midpoint"][0], 200.625)
        self.assertAlmostEqual(pair["midpoint"][1], 200.0)
        self.assertAlmostEqual(pair["forward_distance_m"], 640.0 / 200.25)
        self.assertGreater(pair["distance_m"], pair["forward_distance_m"])

    def test_each_detection_is_used_at_most_once(self):
        detections = [
            detection("buoygreen", [80, 80, 100, 120]),
            detection("buoyred", [280, 82, 300, 122]),
            detection("buoygreen", [200, 280, 230, 340]),
            detection("buoyred", [420, 282, 450, 342]),
        ]

        pairs = pair_buoys(detections, 640, 480)

        self.assertEqual(len(pairs), 2)
        self.assertEqual(
            {(pair["green_index"], pair["red_index"]) for pair in pairs},
            {(0, 1), (2, 3)},
        )

    def test_non_buoy_green_class_is_ignored(self):
        detections = [
            detection("boxgreen", [80, 80, 100, 120]),
            detection("buoyred", [280, 80, 300, 120]),
        ]

        self.assertIsNone(buoy_color(detections[0]))
        self.assertEqual(pair_buoys(detections, 640, 480), [])

    def test_vertical_gap_rejects_unrelated_buoys(self):
        detections = [
            detection("buoygreen", [80, 20, 100, 60]),
            detection("buoyred", [280, 300, 300, 340]),
        ]

        self.assertEqual(pair_buoys(detections, 640, 480), [])

    def test_frontmost_is_global_and_does_not_filter_frame_half(self):
        pairs = [
            {
                "id": 1,
                "distance_m": 2.0,
                "midpoint": (500.0, 300.0),
                "front_y": 330.0,
            },
            {
                "id": 2,
                "distance_m": 8.0,
                "midpoint": (120.0, 280.0),
                "front_y": 390.0,
            },
        ]

        # Target depan berada di kiri frame. Ia tetap harus menang atas target
        # belakang di kanan frame.
        self.assertEqual(frontmost_pair(pairs)["id"], 2)

    def test_focus_side_means_green_position_relative_to_red(self):
        green_right = detection("buoygreen", [390, 190, 410, 210])
        red_left = detection("buoyred", [190, 190, 210, 210])

        self.assertEqual(
            len(pair_buoys([green_right, red_left], 640, 480, focus_side="right")),
            1,
        )
        self.assertEqual(
            pair_buoys([green_right, red_left], 640, 480, focus_side="left"),
            [],
        )

        green_left = detection("buoygreen", [190, 190, 210, 210])
        red_right = detection("buoyred", [390, 190, 410, 210])

        self.assertEqual(
            len(pair_buoys([green_left, red_right], 640, 480, focus_side="left")),
            1,
        )

    def test_right_mode_keeps_front_gate_after_it_crosses_left_frame_half(self):
        detections = [
            # Gerbang TERDEPAN berada di separuh kiri frame, tetapi orientasi
            # internalnya tetap benar: green ada di kanan red.
            detection("buoygreen", [210, 205, 230, 225]),
            detection("buoyred", [90, 205, 110, 225]),
            # Gerbang BELAKANG berada di separuh kanan frame.
            detection("buoygreen", [530, 165, 545, 180]),
            detection("buoyred", [450, 165, 465, 180]),
        ]

        pairs = pair_buoys(
            detections,
            640,
            480,
            focus_side="right",
        )
        target = frontmost_pair(pairs)

        self.assertLess(target["midpoint"][0], 320.0)
        self.assertEqual(target["green_index"], 0)
        self.assertEqual(target["red_index"], 1)

    def test_front_pair_is_matched_before_better_aligned_rear_detection(self):
        detections = [
            # Green paling depan: bottom 207.
            detection("buoygreen", [553, 196, 567, 207]),
            # Green sedikit lebih belakang: bottom 198.
            detection("buoygreen", [506, 188, 518, 198]),
            # Red pasangan depan: bottom 199.
            detection("buoyred", [423, 188, 435, 199]),
            # Red pasangan belakang: bottom 192.
            detection("buoyred", [411, 182, 423, 192]),
        ]

        pairs = pair_buoys(
            detections,
            640,
            480,
            focus_side="right",
        )
        target = frontmost_pair(pairs)

        # Greedy lama mengambil green belakang + red depan karena bottom-gap
        # hanya 1 px. Urutan baru wajib mengamankan pasangan paling depan dulu.
        self.assertEqual(target["green_index"], 0)
        self.assertEqual(target["red_index"], 2)

if __name__ == "__main__":
    unittest.main()
