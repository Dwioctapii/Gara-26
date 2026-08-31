import sys
import types
import unittest
from unittest.mock import patch


# Backend dipilih sebelum OpenCV dipakai. Stub membuat test ini tetap dapat
# dijalankan pada mesin development yang belum memasang dependency vision.
sys.modules.setdefault("cv2", types.ModuleType("cv2"))

import run_pt_video


class BackendSelectionTests(unittest.TestCase):
    def test_explicit_cuda_is_kept(self):
        self.assertEqual(run_pt_video.selected_backend("cuda"), "cuda")

    def test_auto_uses_cuda_on_jetson_architecture(self):
        with (
            patch.object(run_pt_video.sys, "platform", "linux"),
            patch.object(run_pt_video.platform, "machine", return_value="aarch64"),
        ):
            self.assertEqual(run_pt_video.selected_backend("auto"), "cuda")

    def test_auto_keeps_directml_on_windows(self):
        with (
            patch.object(run_pt_video.sys, "platform", "win32"),
            patch.object(run_pt_video.platform, "machine", return_value="AMD64"),
        ):
            self.assertEqual(run_pt_video.selected_backend("auto"), "directml")


if __name__ == "__main__":
    unittest.main()

