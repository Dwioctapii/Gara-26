import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from cuda_engine import YOLOCuda


class _LegacyResult:
    names = {0: "buoyred"}
    speed = {"inference": 1.0}
    boxes = None


class _LegacyYOLO:
    """Meniru Ultralytics Jetson yang names-nya gagal sebelum predict."""

    def __init__(self, *_args, **_kwargs):
        self.model = "best.engine"

    @property
    def names(self):
        raise AttributeError("'str' object has no attribute 'names'")

    def predict(self, **_kwargs):
        return [_LegacyResult()]


class CudaEngineCompatibilityTests(unittest.TestCase):
    def test_legacy_tensorrt_does_not_read_names_before_first_predict(self):
        fake_torch = types.ModuleType("torch")
        fake_torch.cuda = types.SimpleNamespace(
            is_available=lambda: True,
            get_device_name=lambda _index: "Fake Jetson",
        )
        fake_ultralytics = types.ModuleType("ultralytics")
        fake_ultralytics.YOLO = _LegacyYOLO

        with tempfile.TemporaryDirectory() as directory:
            engine_path = Path(directory) / "best.engine"
            engine_path.touch()
            with patch.dict(
                sys.modules,
                {"torch": fake_torch, "ultralytics": fake_ultralytics},
            ):
                engine = YOLOCuda(engine_path, imgsz=32)

        self.assertEqual(engine.names, {0: "buoyred"})


if __name__ == "__main__":
    unittest.main()

