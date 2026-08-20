import re
import unittest
from pathlib import Path

from src.config import SubtitleConfig
from src.models import Scene, TimelineEntry
from src.subtitles import create_cues, format_srt_timestamp


CONFIG = SubtitleConfig(
    font="Arial", font_size=52, margin_bottom=70, outline=3,
    max_chars_per_line=18, max_lines=2,
)


class SubtitleTests(unittest.TestCase):
    def test_srt_timestamp_formatting(self) -> None:
        self.assertEqual(format_srt_timestamp(0), "00:00:00,000")
        self.assertEqual(format_srt_timestamp(3723.456), "01:02:03,456")

    def _sample_cues(self):
        first = "Trước khi mặt trời mọc tại Luân Đôn, Ngân hàng Anh đã chuẩn bị."
        second = "Không thêm hoặc bớt từ."
        timeline = (
            TimelineEntry(Scene(1, "a.mp4", first), Path("a.wav"), 4.0, 0.0, 4.0),
            TimelineEntry(Scene(2, "b.mp4", second), Path("b.wav"), 2.0, 4.0, 6.0),
        )
        return first, second, create_cues(timeline, CONFIG)

    def test_text_preservation(self) -> None:
        first, second, cues = self._sample_cues()
        combined = " ".join(cue.text.replace("\n", " ") for cue in cues)
        expected = f"{first} {second}"
        self.assertEqual(re.sub(r"\s+", " ", combined), expected)

    def test_subtitle_ordering(self) -> None:
        _, _, cues = self._sample_cues()
        self.assertEqual([cue.index for cue in cues], list(range(1, len(cues) + 1)))
        self.assertEqual(cues[0].start, 0.0)
        self.assertEqual(cues[-1].end, 6.0)
        self.assertTrue(all(a.end <= b.start for a, b in zip(cues, cues[1:])))


if __name__ == "__main__":
    unittest.main()
