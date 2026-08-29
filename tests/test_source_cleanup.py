import unittest

import numpy as np

from src.source_cleanup import (
    flow_watermark_alpha, flow_watermark_support_image,
    reconstruct_flow_watermark,
)


class SourceCleanupTests(unittest.TestCase):
    geometry = (1680, 824, 200, 200)

    @staticmethod
    def _textured_frame() -> np.ndarray:
        height, width = 1080, 1920
        yy, xx = np.indices((height, width), dtype=np.float32)
        paper = (
            174.0 + 13.0 * np.sin(xx * 0.19) + 9.0 * np.cos(yy * 0.23)
            + 6.0 * np.sin((xx + yy) * 0.47)
        )
        return np.stack((paper - 8.0, paper, paper + 5.0), axis=2).clip(
            0, 255
        ).astype(np.uint8)

    def _watermarked_pair(self) -> tuple[np.ndarray, np.ndarray]:
        background = self._textured_frame()
        marked = background.copy()
        x, y, width, height = self.geometry
        alpha = np.clip(flow_watermark_alpha(width, height) * 1.35, 0.0, 0.66)
        roi = marked[y:y + height, x:x + width].astype(np.float32)
        marked[y:y + height, x:x + width] = np.clip(
            roi * (1.0 - alpha[:, :, None]) + 248.0 * alpha[:, :, None],
            0, 255,
        ).astype(np.uint8)
        return background, marked

    def test_support_covers_measured_mark_with_margin_not_rectangle(self) -> None:
        support = np.asarray(flow_watermark_support_image(200, 200, 0))
        rows, columns = np.where(support > 0)
        self.assertLessEqual(int(columns.min()), 16)
        self.assertGreaterEqual(int(columns.max()), 104)
        self.assertLessEqual(int(rows.min()), 29)
        self.assertGreaterEqual(int(rows.max()), 123)
        self.assertEqual(int(support[0, 0]), 0)
        self.assertLess(np.count_nonzero(support), 200 * 200 * 0.30)

    def test_reconstruction_is_deterministic_local_and_texture_preserving(self) -> None:
        background, marked = self._watermarked_pair()
        cleaned_a, stats_a = reconstruct_flow_watermark(marked, self.geometry)
        cleaned_b, stats_b = reconstruct_flow_watermark(marked, self.geometry)
        self.assertTrue(np.array_equal(cleaned_a, cleaned_b))
        self.assertEqual(stats_a, stats_b)

        x, y, width, height = self.geometry
        support = np.asarray(
            flow_watermark_support_image(width, height, 0)
        ) > 0
        logo_core = flow_watermark_alpha(width, height) > 0.05
        before = marked[y:y + height, x:x + width].astype(np.float32)
        after = cleaned_a[y:y + height, x:x + width].astype(np.float32)
        expected = background[y:y + height, x:x + width].astype(np.float32)
        before_error = float(np.mean(np.abs(before[logo_core] - expected[logo_core])))
        after_error = float(np.mean(np.abs(after[logo_core] - expected[logo_core])))
        self.assertLess(after_error, before_error * 0.75)

        expected_variance = float(np.var(expected[support]))
        repaired_variance = float(np.var(after[support]))
        self.assertGreater(repaired_variance, expected_variance * 0.35)
        self.assertLess(repaired_variance, expected_variance * 2.2)

        changed = np.any(cleaned_a != marked, axis=2)
        full_support = np.zeros(changed.shape, dtype=bool)
        full_support[y:y + height, x:x + width] = np.asarray(
            flow_watermark_support_image(width, height, 6)
        ) > 0
        self.assertFalse(np.any(changed & ~full_support))
        self.assertLess(np.count_nonzero(changed), marked.shape[0] * marked.shape[1] * 0.01)

    def test_clean_high_contrast_frame_is_bit_identical(self) -> None:
        frame = np.full((1080, 1920, 3), 190, dtype=np.uint8)
        frame[824:1024, 1680:1880:20] = 20
        cleaned, stats = reconstruct_flow_watermark(frame, self.geometry)
        self.assertTrue(np.array_equal(cleaned, frame))
        self.assertEqual(stats["method"], "pass_through")


if __name__ == "__main__":
    unittest.main()
