import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.layered_composer import compose_frame, layer_state_at
from src.layered_manifest import (
    ENTER_PRESETS, CameraMotion, LayerItem, LayerState, LayeredSceneManifest, SceneTransition,
)


class LayeredComposerTests(unittest.TestCase):
    def item(self, enter: str, *, z: int = 1) -> LayerItem:
        return LayerItem(
            id=enter, file=f"{enter}.png", state=LayerState(100, 60, 1, 0, 1),
            z=z, start=0.5, duration=0.5, enter=enter, anchor="center",
        )

    def test_all_animation_presets_are_invisible_before_start_and_settle(self) -> None:
        for enter in ENTER_PRESETS:
            with self.subTest(enter=enter):
                item = self.item(enter)
                before, reveal_before = layer_state_at(item, 0.2, 3.0)
                settled, reveal_settled = layer_state_at(item, 1.1, 3.0)
                self.assertEqual(before.opacity, 0.0)
                self.assertEqual(reveal_before, 0.0)
                self.assertAlmostEqual(settled.x, item.state.x)
                self.assertAlmostEqual(settled.y, item.state.y)
                self.assertAlmostEqual(settled.scale, item.state.scale)
                self.assertAlmostEqual(reveal_settled, 1.0)

    def test_end_state_interpolates_only_after_entrance(self) -> None:
        item = self.item("scale_in")
        item = LayerItem(**{**item.__dict__, "end_state": LayerState(140, 80, 1.1, 4, 0.8)})
        during, _ = layer_state_at(item, 0.75, 3.0)
        finished, _ = layer_state_at(item, 3.0, 3.0)
        self.assertLess(during.x, 101)
        self.assertAlmostEqual(finished.x, 140)
        self.assertAlmostEqual(finished.opacity, 0.8)

    def test_composite_respects_z_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            back = LayerItem("back", "back.png", LayerState(50, 50, 1, 0, 1), 1, 0, 0.1, "scale_in", "center")
            front = LayerItem("front", "front.png", LayerState(50, 50, 1, 0, 1), 2, 0, 0.1, "scale_in", "center")
            manifest = LayeredSceneManifest(
                root, 100, 100, "background.png", (back, front), CameraMotion(), SceneTransition()
            )
            images = {
                "background.png": Image.new("RGBA", (100, 100), "white"),
                "back.png": Image.new("RGBA", (60, 60), "red"),
                "front.png": Image.new("RGBA", (30, 30), "blue"),
            }
            frame = compose_frame(manifest, 1.0, 2.0, images)
        self.assertEqual(frame.getpixel((50, 50)), (0, 0, 255))
        self.assertEqual(frame.getpixel((25, 50)), (255, 0, 0))


if __name__ == "__main__":
    unittest.main()
