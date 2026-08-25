import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.config import load_config
from src.visual_quality import (
    _logo_score, ensure_flow_gemini_mask, source_cleanup_geometry,
    source_edge_crop_geometry,
)


ROOT = Path(__file__).resolve().parents[1]


class VisualQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(ROOT / "config.json")

    def test_cleanup_geometry_matches_verified_flow_region(self) -> None:
        self.assertEqual(
            source_cleanup_geometry(1920, 1080, self.config.source_cleanup),
            (1680, 824, 200, 200),
        )
        self.assertEqual(
            source_edge_crop_geometry(1920, 1080, self.config.source_cleanup),
            (1700, 956),
        )

    def test_generated_mask_is_feathered_and_covers_two_sparkles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = ensure_flow_gemini_mask(
                Path(directory), 1920, 1080, self.config.source_cleanup
            )
            from PIL import Image
            pixels = np.asarray(Image.open(path).convert("L"))
        self.assertEqual(pixels.shape, (200, 200))
        self.assertGreater(pixels[75, 60], 240)
        self.assertGreater(pixels[126, 125], 240)
        self.assertTrue(np.any((pixels > 0) & (pixels < 255)))

    def test_logo_score_detects_bright_sparkle_pattern(self) -> None:
        frames = np.full((3, 180, 320), 100, dtype=np.uint8)
        x, y, width, height = source_cleanup_geometry(
            320, 180, self.config.source_cleanup
        )
        frames[1, y:y + height, x:x + width] = 100
        frames[1, y + 2:y + height // 2, x + width // 4:x + width // 2] = 230
        self.assertGreater(_logo_score(frames, self.config.source_cleanup), 0.015)


if __name__ == "__main__":
    unittest.main()
