import unittest

from src.visual_continuity import static_run_metrics


class VisualContinuityMetricTests(unittest.TestCase):
    def test_longest_static_run_ignores_separated_motion(self) -> None:
        longest, leading = static_run_metrics(
            (False, False, True, False, False, False, True), 1000 / 30
        )
        self.assertAlmostEqual(longest, 100.0)
        self.assertAlmostEqual(leading, 2000 / 30)

    def test_all_motion_has_no_static_dead_zone(self) -> None:
        longest, leading = static_run_metrics((True, True, True), 1000 / 30)
        self.assertEqual((longest, leading), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
