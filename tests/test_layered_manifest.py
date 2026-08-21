import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.layered_manifest import ENTER_PRESETS, load_layered_manifest
from src.models import AutoEditorError


class LayeredManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "scene_01"
        self.root.mkdir()
        Image.new("RGB", (320, 180), "#eee2c8").save(self.root / "background.jpg")
        Image.new("RGBA", (80, 60), (220, 40, 30, 255)).save(self.root / "item.png")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, **changes) -> None:
        data = {
            "canvas": {"width": 320, "height": 180},
            "background": "background.jpg",
            "items": [
                {"id": "front", "file": "item.png", "x": 160, "y": 90,
                 "z": 5, "start": 0.4, "duration": 0.5, "enter": "stamp_in"},
                {"id": "back", "file": "item.png", "x": 120, "y": 80,
                 "z": 1, "start": 0.0, "duration": 0.3, "enter": "slide_left_fade"},
            ],
            "camera": {"type": "drift", "x": 4, "y": 2, "zoom": 1.02},
            "transition_out": {"type": "paper_wipe", "duration": 0.4},
        }
        data.update(changes)
        (self.root / "manifest.json").write_text(json.dumps(data), encoding="utf-8")

    def test_valid_manifest_sorts_z_and_parses_timing_camera_transition(self) -> None:
        self.write()
        manifest = load_layered_manifest(self.root, expected_width=320, expected_height=180)
        self.assertEqual([item.id for item in manifest.items], ["back", "front"])
        self.assertAlmostEqual(manifest.build_complete, 0.9)
        self.assertEqual(manifest.camera.type, "drift")
        self.assertEqual(manifest.transition_out.type, "paper_wipe")

    def test_every_required_enter_preset_validates(self) -> None:
        for preset in ENTER_PRESETS:
            with self.subTest(preset=preset):
                self.write(items=[{
                    "id": "one", "file": "item.png", "x": 160, "y": 90,
                    "start": 0, "duration": 0.2, "enter": preset,
                }])
                self.assertEqual(load_layered_manifest(self.root).items[0].enter, preset)

    def test_path_traversal_duplicate_id_and_bad_canvas_fail(self) -> None:
        cases = [
            ({"background": "../secret.png"}, "basename an toàn"),
            ({"items": [
                {"id": "same", "file": "item.png", "x": 1, "y": 1},
                {"id": "same", "file": "item.png", "x": 2, "y": 2},
            ]}, "bị trùng"),
            ({"canvas": {"width": 0, "height": 180}}, "canvas.width"),
        ]
        for changes, message in cases:
            with self.subTest(message=message):
                self.write(**changes)
                with self.assertRaisesRegex(AutoEditorError, message):
                    load_layered_manifest(self.root)


if __name__ == "__main__":
    unittest.main()
