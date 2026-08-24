import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from src.alignment import (
    align_continuous_narration,
    align_timeline,
    canonical_words,
    to_global_words,
    validate_and_map_words,
    WhisperXAlignmentEngine,
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
    def test_whisperx_386_public_api_contract_without_model_download(self) -> None:
        calls: dict[str, object] = {}
        loads: list[dict[str, object]] = []
        fake = types.ModuleType("whisperx")

        def load_align_model(**kwargs):
            loads.append(kwargs)
            return "model", {"language": kwargs["language_code"]}

        def load_audio(path):
            calls["audio"] = path
            return "audio"

        def align(transcript, model, metadata, audio, device, **kwargs):
            calls["align"] = {
                "transcript": transcript, "model": model, "metadata": metadata,
                "audio": audio, "device": device, **kwargs,
            }
            return {"segments": [], "word_segments": raw_words()}

        fake.load_align_model = load_align_model
        fake.load_audio = load_audio
        fake.align = align
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {"whisperx": fake}):
            engine = WhisperXAlignmentEngine("en", config(Path(directory)))
            result = engine.align(Path("scene.wav"), "Before sunrise in London", 1.5)
            WhisperXAlignmentEngine("vi", config(Path(directory)))
        self.assertEqual(result, raw_words())
        self.assertEqual([item["language_code"] for item in loads], ["en", "vi"])
        self.assertTrue(all(item["model_name"] is None for item in loads))
        self.assertEqual(calls["align"]["interpolate_method"], "ignore")
        self.assertFalse(calls["align"]["return_char_alignments"])
        self.assertEqual(
            calls["align"]["transcript"],
            [{"text": "Before sunrise in London", "start": 0.0, "end": 1.5}],
        )

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

    def test_continuous_alignment_maps_every_word_to_one_scene(self) -> None:
        scenes = (
            Scene(1, "a.mp4", "One two."),
            Scene(2, "b.mp4", "Three four."),
        )
        raw = [
            {"word": "One", "start": 0.05, "end": 0.25},
            {"word": "two", "start": 0.30, "end": 0.55},
            {"word": "Three", "start": 0.68, "end": 0.90},
            {"word": "four", "start": 0.95, "end": 1.20},
        ]
        engine = FakeEngine(raw)
        with tempfile.TemporaryDirectory() as directory:
            timeline, alignments = align_continuous_narration(
                scenes, Path("voice.wav"), 1.30, "en", config(Path(directory)),
                Path(directory) / "alignment", engine,
            )
        self.assertEqual(engine.calls, 1)
        self.assertEqual([word.word for word in alignments[0].words], ["One", "two."])
        self.assertEqual([word.word for word in alignments[1].words], ["Three", "four."])
        self.assertAlmostEqual(timeline[1].start, 0.68)
        self.assertAlmostEqual(alignments[1].words[0].start, 0.0)
        self.assertEqual(
            sum(len(alignment.words) for alignment in alignments),
            sum(len(canonical_words(scene.text)) for scene in scenes),
        )

    def test_continuous_alignment_diagnostics_preserve_scene_ownership(self) -> None:
        scenes = (Scene(1, "a.mp4", "One."), Scene(2, "b.mp4", "Two."))
        raw = [
            {"word": "One", "start": 0.02, "end": 0.30},
            {"word": "Two", "start": 0.42, "end": 0.75},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            align_continuous_narration(
                scenes, Path("voice.wav"), 0.85, "en", config(root),
                root / "alignment", FakeEngine(raw),
            )
            master = json.loads(
                (root / "alignment" / "continuous_master.json").read_text(encoding="utf-8")
            )
            first = json.loads(
                (root / "alignment" / "scene_001.json").read_text(encoding="utf-8")
            )
        self.assertEqual(master["scene_word_counts"], {"1": 1, "2": 1})
        self.assertEqual(master["canonical_count"], master["aligned_count"])
        self.assertEqual(first["timeline_start"], 0.0)
        self.assertEqual(first["timeline_end"], 0.42)

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

    def test_standalone_em_dash_attaches_to_previous_word(self) -> None:
        text = "Britain was trapped — and pressure increased."
        raw = [
            {"word": word, "start": index * 0.2, "end": index * 0.2 + 0.15}
            for index, word in enumerate(("Britain", "was", "trapped", "and", "pressure", "increased"))
        ]
        mapped = validate_and_map_words(text, raw, 2.0, 0.1)
        self.assertEqual(
            [word.word for word in mapped],
            ["Britain", "was", "trapped —", "and", "pressure", "increased."],
        )

    def test_standalone_arrow_attaches_without_fake_timing(self) -> None:
        text = "The rate moved from 10% → 12%."
        raw = [
            {"word": "The", "start": 0.0, "end": 0.15},
            {"word": "rate", "start": 0.2, "end": 0.35},
            {"word": "moved", "start": 0.4, "end": 0.55},
            {"word": "from", "start": 0.6, "end": 0.75},
            {"word": "10", "start": 0.8, "end": 0.95},
            {"word": "12", "start": 1.05, "end": 1.2},
        ]
        mapped = validate_and_map_words(text, raw, 1.3, 0.1)
        self.assertEqual(
            [word.word for word in mapped],
            ["The", "rate", "moved", "from", "10% →", "12%."],
        )

    def test_colon_and_ellipsis_are_preserved(self) -> None:
        self.assertEqual(canonical_words("London: the pound fell."), ("London:", "the", "pound", "fell."))
        self.assertEqual(canonical_words("Wait ... then continue."), ("Wait ...", "then", "continue."))

    def test_vietnamese_punctuation_and_multiple_spaces(self) -> None:
        text = "Trước   bình minh   —   đồng bảng chịu áp lực."
        self.assertEqual(
            canonical_words(text),
            ("Trước", "bình", "minh —", "đồng", "bảng", "chịu", "áp", "lực."),
        )


if __name__ == "__main__":
    unittest.main()
