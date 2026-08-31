import unittest

from state import StateStore


class StatePerformanceTests(unittest.TestCase):
    def test_gui_snapshot_excludes_large_mission(self):
        store = StateStore()
        store.replace_mission([{"seq": index} for index in range(100)])

        snapshot = store.gui_snapshot()

        self.assertNotIn("mission", snapshot)
        self.assertIn("gps", snapshot)
        self.assertIn("serial", snapshot)

    def test_frame_sequence_changes_only_when_published(self):
        store = StateStore()
        frame = object()

        self.assertEqual(store.latest_frame(), (0, None))
        store.publish_frame(frame)
        sequence, published = store.latest_frame()

        self.assertEqual(sequence, 1)
        self.assertIs(published, frame)

    def test_vision_snapshot_contains_only_vision_state(self):
        store = StateStore()

        snapshot = store.vision_snapshot()

        self.assertEqual(set(snapshot), {"detection", "pid_config"})


if __name__ == "__main__":
    unittest.main()
