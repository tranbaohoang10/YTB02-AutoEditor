import json
import tempfile
import unittest
from pathlib import Path

from src.alignment import (
    align_timeline,
    canonical_words,
    to_global_words,
    validate_and_map_words,
)
from src.config import AlignmentConfig
from src.models import AutoEditorError, Scene, SceneAlignment, TimelineEntry, WordTiming


def config(root: Path, *, fallback: bool = False) -> AlignmentConfig:
    return AlignmentConfig(
        engine="whisperx", device="cpu", allow_approximate_fallback=fallback,
        model_en=None, model_vi=None, cache_dir=root / "cache", duration_tolerance=0.25,
    )


def raw_words() -> list[dict[str, object]]:
    return [
        {"word": "Before", "start": 0.0, "end": 0.25},
        {"word": "sunrise", "start": 0.3, "end": 0.65},
        {"word": "in", "start": 0.7, "end": 0.85},
        {"word": "London", "start": 0.9, "end": 1.2},
    ]


class FakeEngine:
    def __init__(self, words: list[dict[str, object]]) -> None:
        self.words = words
        self.calls = 0

    def align(self, audio_path: Path, text: str, duration: float):
        self.calls += 1
        return self.words


class AlignmentTests(unittest.TestCase):
    def test_canonical_words_preserved_with_punctuation(self) -> None:
        mapped = validate_and_map_words("Before sunrise in London.", raw_words(), 1.5, 0.25)
        self.assertEqual([word.word for word in mapped], ["Before", "sunrise", "in", "London."])

    def test_vietnamese_canonical_diacritics_preserved(self) -> None:
        raw = [
            {"word": "Trước", "start": 0.0, "end": 0.2},
            {"word": "bình", "start": 0.25, "end": 0.45},
            {"word": "minh", "start": 0.5, "end": 0.75},
        ]
        mapped = validate_and_map_words("Trước bình minh.", raw, 1.0, 0.1)
        self.assertEqual([word.word for word in mapped], ["Trước", "bình", "minh."])

    def test_word_timings_monotonically_ordered(self) -> None:
        mapped = validate_and_map_words("Before sunrise in London", raw_words(), 1.5, 0.1)
        self.assertTrue(all(a.start <= b.start for a, b in zip(mapped, mapped[1:])))

    def test_missing_canonical_word_rejected(self) -> None:
        with self.assertRaisesRegex(AutoEditorError, "không khớp"):
            validate_and_map_words("Before sunrise in London", raw_words()[:-1], 1.5, 0.1)

    def test_extra_aligned_word_rejected(self) -> None:
        extra = [*raw_words(), {"word": "today", "start": 1.25, "end": 1.4}]
        with self.assertRaisesRegex(AutoEditorError, "thêm word"):
            validate_and_map_words("Before sunrise in London", extra, 1.5, 0.1)

    def test_non_monotonic_timestamp_rejected(self) -> None:
        raw = raw_words()
        raw[2] = {"word": "in", "start": 0.1, "end": 0.2}
        with self.assertRaisesRegex(AutoEditorError, "thứ tự"):
            validate_and_map_words("Before sunrise in London", raw, 1.5, 0.1)

    def test_missing_timestamp_rejected(self) -> None:
        raw = raw_words()
        raw[1] = {"word": "sunrise", "start": 0.3}
        with self.assertRaisesRegex(AutoEditorError, "thiếu start/end"):
            validate_and_map_words("Before sunrise in London", raw, 1.5, 0.1)

    def test_word_end_beyond_audio_duration_rejected(self) -> None:
        raw = raw_words()
        raw[-1] = {"word": "London", "start": 0.9, "end": 2.0}
        with self.assertRaisesRegex(AutoEditorError, "sau scene audio duration"):
            validate_and_map_words("Before sunrise in London", raw, 1.5, 0.1)

    def test_scene_relative_to_global_timestamp(self) -> None:
        alignment = SceneAlignment(2, "en", (WordTiming("word", 0.3, 0.6),))
        global_words = to_global_words(alignment, 4.5)
        self.assertAlmostEqual(global_words[0].start, 4.8)
        self.assertAlmostEqual(global_words[0].end, 5.1)

    def test_one_engine_reused_for_multiple_scenes(self) -> None:
        scenes = (
            TimelineEntry(Scene(1, "a.mp4", "Before sunrise in London"), Path("a.wav"), 1.5, 0.0, 1.5),
            TimelineEntry(Scene(2, "b.mp4", "Before sunrise in London"), Path("b.wav"), 1.5, 1.5, 3.0),
        )
        engine = FakeEngine(raw_words())
        with tempfile.TemporaryDirectory() as directory:
            results = align_timeline(scenes, "en", config(Path(directory)), Path(directory) / "out", engine)
        self.assertEqual(len(results), 2)
        self.assertEqual(engine.calls, 2)

    def test_failed_alignment_writes_diagnostics_and_raises_clear_error(self) -> None:
        scene = TimelineEntry(
            Scene(7, "a.mp4", "Before sunrise in London"), Path("a.wav"), 1.5, 0.0, 1.5
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "alignment"
            with self.assertRaisesRegex(AutoEditorError, "scene 07"):
                align_timeline((scene,), "en", config(Path(directory)), output, FakeEngine(raw_words()[:-1]))
            diagnostics = json.loads((output / "scene_007.json").read_text(encoding="utf-8"))
        self.assertEqual(diagnostics["status"], "failed")
        self.assertEqual(diagnostics["canonical_count"], 4)

    def test_approximate_fallback_is_off_and_not_silent(self) -> None:
        self.assertFalse(config(Path("cache")).allow_approximate_fallback)
        scene = TimelineEntry(Scene(1, "a.mp4", "One"), Path("a.wav"), 1.0, 0.0, 1.0)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AutoEditorError, "Approximate"):
                align_timeline(
                    (scene,), "en", config(Path(directory), fallback=True),
                    Path(directory) / "out", FakeEngine([]),
                )

    def test_canonical_tokenizer_does_not_rewrite_text(self) -> None:
        self.assertEqual(canonical_words("Xin chào, Việt Nam!"), ("Xin", "chào,", "Việt", "Nam!"))


if __name__ == "__main__":
    unittest.main()
