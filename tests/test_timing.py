import tempfile
import unittest
from pathlib import Path

from src.models import Scene
from src.timing import build_timeline


class TimingTests(unittest.TestCase):
    def test_cumulative_duration_with_gap(self) -> None:
        scenes = (
            Scene(1, "one.mp4", "One"),
            Scene(2, "two.mp4", "Two"),
            Scene(3, "three.mp4", "Three"),
        )
        durations = {"scene_001.wav": 3.72, "scene_002.wav": 5.18, "scene_003.wav": 4.31}
        with tempfile.TemporaryDirectory() as directory:
            timeline = build_timeline(
                scenes, Path(directory), lambda path: durations[path.name], gap_ms=100
            )
        self.assertAlmostEqual(timeline[0].start, 0.0)
        self.assertAlmostEqual(timeline[0].end, 3.72)
        self.assertAlmostEqual(timeline[1].start, 3.82)
        self.assertAlmostEqual(timeline[1].end, 9.0)
        self.assertAlmostEqual(timeline[2].start, 9.1)
        self.assertAlmostEqual(timeline[2].end, 13.41)


if __name__ == "__main__":
    unittest.main()
