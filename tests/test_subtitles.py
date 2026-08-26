import tempfile
import unittest
from pathlib import Path

from src.config import SubtitleConfig
from src.models import Scene, SceneAlignment, TimelineEntry, WordTiming
from src.subtitles import (
    create_rolling_cues,
    create_subtitle_phrases,
    format_ass_timestamp,
    format_srt_timestamp,
    write_ass,
    write_phrase_ass,
    write_srt,
    write_subtitle_diagnostics,
)


CONFIG = SubtitleConfig(
    font="Arial", font_size=52, margin_bottom=70, outline=3,
    max_chars_per_line=18, max_lines=2, max_words_per_window=4,
)


def sample_scene() -> tuple[tuple[TimelineEntry, ...], tuple[SceneAlignment, ...]]:
    text = "Before sunrise in London"
    timeline = (
        TimelineEntry(Scene(1, "a.mp4", text), Path("a.wav"), 1.5, 0.0, 1.5),
    )
    alignment = (
        SceneAlignment(1, "en", (
            WordTiming("Before", 0.0, 0.25),
            WordTiming("sunrise", 0.3, 0.65),
            WordTiming("in", 0.7, 0.85),
            WordTiming("London", 0.9, 1.2),
        )),
    )
    return timeline, alignment


class SubtitleTests(unittest.TestCase):
    def test_srt_timestamp_formatting(self) -> None:
        self.assertEqual(format_srt_timestamp(0), "00:00:00,000")
        self.assertEqual(format_srt_timestamp(3723.456), "01:02:03,456")

    def test_serialized_timestamp_never_rounds_early(self) -> None:
        self.assertEqual(format_srt_timestamp(0.3004), "00:00:00,301")
        self.assertEqual(format_ass_timestamp(0.304), "0:00:00.31")

    def test_future_word_invariant_at_half_second(self) -> None:
        timeline, alignments = sample_scene()
        cues = create_rolling_cues(alignments, timeline, CONFIG)
        visible = next(cue.text.replace("\n", " ") for cue in cues if cue.start <= 0.5 < cue.end)
        self.assertEqual(visible, "Before sunrise")
        self.assertNotIn(" in", visible)
        self.assertNotIn("London", visible)

    def test_every_event_contains_only_started_words(self) -> None:
        timeline, alignments = sample_scene()
        cues = create_rolling_cues(alignments, timeline, CONFIG)
        starts = {word.word: word.start for word in alignments[0].words}
        for cue in cues:
            for word in cue.text.replace("\n", " ").split():
                self.assertLessEqual(starts[word], cue.start)

    def test_window_rollover_never_reveals_future_word(self) -> None:
        timeline, alignments = sample_scene()
        config = SubtitleConfig("Arial", 52, 70, 3, 42, 2, 2)
        cues = create_rolling_cues(alignments, timeline, config)
        at_075 = next(cue.text.replace("\n", " ") for cue in cues if cue.start <= 0.75 < cue.end)
        self.assertEqual(at_075, "in")
        self.assertNotIn("London", at_075)

    def test_attached_punctuation_does_not_reveal_future_spoken_word(self) -> None:
        text = "Britain was trapped — and pressure increased."
        timeline = (TimelineEntry(Scene(1, "a.mp4", text), Path("a.wav"), 2.0, 0.0, 2.0),)
        alignments = (
            SceneAlignment(1, "en", (
                WordTiming("Britain", 0.0, 0.2),
                WordTiming("was", 0.3, 0.45),
                WordTiming("trapped —", 0.5, 0.8),
                WordTiming("and", 1.0, 1.15),
                WordTiming("pressure", 1.2, 1.5),
                WordTiming("increased.", 1.55, 1.8),
            )),
        )
        cues = create_rolling_cues(alignments, timeline, CONFIG)
        visible = next(cue.text.replace("\n", " ") for cue in cues if cue.start <= 0.9 < cue.end)
        self.assertIn("trapped —", visible)
        self.assertNotIn(" and", visible)

    def test_max_lines_formatting(self) -> None:
        timeline, alignments = sample_scene()
        cues = create_rolling_cues(alignments, timeline, CONFIG)
        self.assertTrue(all(len(cue.text.splitlines()) <= 2 for cue in cues))

    def test_global_offset_for_second_scene(self) -> None:
        scene = Scene(2, "b.mp4", "Xin chào")
        timeline = (TimelineEntry(scene, Path("b.wav"), 1.5, 4.5, 6.0),)
        alignments = (
            SceneAlignment(2, "vi", (
                WordTiming("Xin", 0.3, 0.5), WordTiming("chào", 0.7, 1.0),
            )),
        )
        cues = create_rolling_cues(alignments, timeline, CONFIG)
        self.assertAlmostEqual(cues[0].start, 4.8)
        self.assertAlmostEqual(cues[1].start, 5.2)

    def test_srt_and_ass_event_ordering(self) -> None:
        timeline, alignments = sample_scene()
        cues = create_rolling_cues(alignments, timeline, CONFIG)
        self.assertEqual([cue.index for cue in cues], list(range(1, len(cues) + 1)))
        self.assertTrue(all(left.end <= right.start for left, right in zip(cues, cues[1:])))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_srt(cues, root / "test.srt")
            write_ass(cues, root / "test.ass", CONFIG, 1920, 1080)
            srt = (root / "test.srt").read_text(encoding="utf-8")
            ass = (root / "test.ass").read_text(encoding="utf-8-sig")
        self.assertIn("Before sunrise", srt)
        self.assertIn("Dialogue: 0,0:00:00.30,0:00:00.70", ass)

    def test_continuous_scene_boundary_never_reveals_next_scene_early(self) -> None:
        scenes = (
            Scene(1, "a.mp4", "One ends."),
            Scene(2, "b.mp4", "Next begins."),
        )
        timeline = (
            TimelineEntry(scenes[0], Path("voice.wav"), 0.70, 0.0, 0.70),
            TimelineEntry(scenes[1], Path("voice.wav"), 0.70, 0.70, 1.40),
        )
        alignments = (
            SceneAlignment(1, "en", (
                WordTiming("One", 0.05, 0.25), WordTiming("ends.", 0.30, 0.55),
            )),
            SceneAlignment(2, "en", (
                WordTiming("Next", 0.0, 0.25), WordTiming("begins.", 0.30, 0.60),
            )),
        )
        cues = create_rolling_cues(alignments, timeline, CONFIG)
        before_boundary = [cue.text for cue in cues if cue.start < 0.70]
        self.assertTrue(all("Next" not in text for text in before_boundary))
        next_cue = next(cue for cue in cues if "Next" in cue.text)
        self.assertGreaterEqual(next_cue.start, 0.70)

    def test_phrase_layout_hold_karaoke_and_diagnostics_are_stable(self) -> None:
        timeline, alignments = sample_scene()
        phrases = create_subtitle_phrases(alignments, timeline, CONFIG)
        self.assertEqual(len(phrases), 1)
        self.assertEqual(len(phrases[0].words), 4)
        self.assertAlmostEqual(phrases[0].end - phrases[0].words[-1].end, 0.3)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_phrase_ass(phrases, root / "phrases.ass", CONFIG, 1920, 1080)
            diagnostics = write_subtitle_diagnostics(
                phrases, root / "subtitles.json", CONFIG
            )
            ass = (root / "phrases.ass").read_text(encoding="utf-8-sig")
        self.assertEqual(ass.count("Dialogue: 0,"), 1)
        self.assertIn("SecondaryColour", ass)
        self.assertIn("&HFFFFFFFF", ass)
        self.assertIn(r"{\ko30}Before", ass)
        self.assertIn(r"\N", ass)
        self.assertEqual(diagnostics["phrase_count"], 1)
        self.assertEqual(diagnostics["phrases"][0]["hold_ms"], 300)

    def test_readability_style_keeps_future_words_transparent(self) -> None:
        timeline, alignments = sample_scene()
        phrases = create_subtitle_phrases(alignments, timeline, CONFIG)
        readable = SubtitleConfig(
            "Arial", 56, 78, 4, 42, 2, 8, 4, 8, 250, 450, 22.0,
            True, 2, 100,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "readable.ass"
            write_phrase_ass(phrases, path, readable, 1920, 1080)
            ass = path.read_text(encoding="utf-8-sig")
        self.assertIn("&HFFFFFFFF", ass)
        self.assertIn(", -1,", ass.replace(",-1,", ", -1,"))
        self.assertIn("&HFF000000", ass)
        self.assertIn(",1,4,0,2,100,100,78,1", ass)

    def test_dense_scene_gets_stronger_current_text_only_outline(self) -> None:
        timeline, alignments = sample_scene()
        phrases = create_subtitle_phrases(alignments, timeline, CONFIG)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dense.ass"
            write_phrase_ass(
                phrases, path, CONFIG, 1920, 1080,
                dense_scene_ids={phrases[0].scene_id},
            )
            ass = path.read_text(encoding="utf-8-sig")
        self.assertIn(r"{\bord5}{\ko30}Before", ass)
        self.assertIn("&HFFFFFFFF", ass)
        self.assertNotIn(r"{\bord5}Next", ass)


if __name__ == "__main__":
    unittest.main()
