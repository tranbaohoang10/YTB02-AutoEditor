import json
import math
import struct
import tempfile
import unittest
import wave
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.config import load_config
from src.models import Scene, SceneAlignment, TimelineEntry, WordTiming
from src.transitions import (
    avoid_source_sfx_conflicts, build_transition_sfx_mix,
    schedule_pause_aware_transitions, write_transition_diagnostics,
)


ROOT = Path(__file__).resolve().parents[1]


def _fixture(boundary_pause: float, internal_pause: float = 0.05):
    first = Scene(1, "scene_01.mp4", "First phrase ends.")
    second = Scene(2, "scene_02.mp4", "Second phrase starts.")
    timeline = (
        TimelineEntry(first, Path("voice.wav"), 2.0, 0.0, 2.0),
        TimelineEntry(second, Path("voice.wav"), 2.0, 2.0, 4.0),
    )
    alignments = (
        SceneAlignment(1, "en", (
            WordTiming("First", 0.10, 0.40),
            WordTiming("phrase", 0.40 + internal_pause, 0.90),
            WordTiming("ends.", 1.20, 2.0 - boundary_pause),
        )),
        SceneAlignment(2, "en", (
            WordTiming("Second", 0.0, 0.25), WordTiming("starts.", 0.30, 0.60),
        )),
    )
    return timeline, alignments


class PauseAwareTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(ROOT / "config.json")

    def test_pause_below_threshold_has_no_transition(self) -> None:
        timeline, alignments = _fixture(0.20)
        decision = schedule_pause_aware_transitions(
            timeline, alignments, self.config.transitions
        )[0]
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.effect, "none")
        self.assertEqual(decision.reason, "below_threshold")

    def test_eligible_scene_boundary_is_a_transition_candidate(self) -> None:
        timeline, alignments = _fixture(0.50)
        decision = schedule_pause_aware_transitions(
            timeline, alignments, self.config.transitions
        )[0]
        self.assertTrue(decision.eligible)
        self.assertTrue(decision.has_visual)
        self.assertEqual(decision.pause_class, "scene_boundary")

    def test_transition_fits_pause_and_does_not_change_narration_timeline(self) -> None:
        timeline, alignments = _fixture(0.38)
        before = tuple((entry.start, entry.end) for entry in timeline)
        decision = schedule_pause_aware_transitions(
            timeline, alignments,
            replace(self.config.transitions, strong_trigger_ms=350),
        )[0]
        self.assertLessEqual(decision.visual_duration, decision.pause_seconds)
        self.assertGreaterEqual(decision.visual_start, decision.pause_start)
        self.assertAlmostEqual(decision.visual_start + decision.visual_duration,
                               decision.pause_end)
        self.assertEqual(before, tuple((entry.start, entry.end) for entry in timeline))

    def test_internal_pause_never_receives_major_transition(self) -> None:
        timeline, alignments = _fixture(0.20, internal_pause=0.35)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transitions.json"
            decisions = schedule_pause_aware_transitions(
                timeline, alignments, self.config.transitions
            )
            report = write_transition_diagnostics(decisions, timeline, alignments, path)
        internal = report["internal_pauses"]["records"]
        self.assertTrue(any(record["pause_ms"] >= 300 for record in internal))
        self.assertTrue(all(record["effect"] == "none" for record in internal))

    def test_missing_sfx_asset_keeps_visual_transition(self) -> None:
        timeline, alignments = _fixture(0.50)
        config = replace(self.config.transitions, sfx_dir=ROOT / "missing-sfx")
        decision = schedule_pause_aware_transitions(timeline, alignments, config)[0]
        self.assertTrue(decision.has_visual)
        self.assertFalse(decision.has_sfx)
        self.assertEqual(decision.reason, "scheduled_visual_missing_sfx")

    def test_available_sfx_is_scheduled_at_visual_start(self) -> None:
        timeline, alignments = _fixture(0.50)
        decision = schedule_pause_aware_transitions(
            timeline, alignments, self.config.transitions
        )[0]
        self.assertTrue(decision.has_sfx)
        self.assertEqual(decision.sfx_start, decision.visual_start)

    def test_transition_sfx_mix_fades_trims_and_never_loops(self) -> None:
        timeline, alignments = _fixture(0.50)
        decisions = schedule_pause_aware_transitions(
            timeline, alignments, self.config.transitions
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.transitions.probe_audio_duration", return_value=0.30
        ), patch("src.transitions.run_media_command") as run:
            built = build_transition_sfx_mix(
                decisions, Path(directory) / "transition.wav", 4.0, self.config
            )
        self.assertTrue(built)
        graph = run.call_args.args[0][run.call_args.args[0].index("-filter_complex") + 1]
        self.assertIn("atrim=start=0:duration=0.300000", graph)
        self.assertIn("volume=-19.000dB", graph)
        self.assertIn("afade=t=in", graph)
        self.assertIn("afade=t=out", graph)
        self.assertNotIn("aloop", graph)

    def test_strong_source_sfx_suppresses_duplicate_transition_accent(self) -> None:
        timeline, alignments = _fixture(0.50)
        decisions = schedule_pause_aware_transitions(
            timeline, alignments, self.config.transitions
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.wav"
            samples = [12000] * (4 * 48_000 * 2)
            with wave.open(str(source), "wb") as output:
                output.setnchannels(2)
                output.setsampwidth(2)
                output.setframerate(48_000)
                output.writeframes(struct.pack(f"<{len(samples)}h", *samples))
            checked = avoid_source_sfx_conflicts(
                decisions, source, self.config.transitions
            )
        self.assertFalse(checked[0].has_sfx)
        self.assertEqual(checked[0].reason, "visual_only_source_sfx_conflict")

    def test_diagnostics_reports_effect_and_untouched_counts(self) -> None:
        timeline, alignments = _fixture(0.50)
        decisions = schedule_pause_aware_transitions(
            timeline, alignments, self.config.transitions
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transitions.json"
            report = write_transition_diagnostics(decisions, timeline, alignments, path)
            persisted = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(report["visual_effect_count"], 1)
        self.assertFalse(report["narration_timeline_changed"])
        self.assertEqual(persisted["boundaries"][0]["from_scene"], 1)


if __name__ == "__main__":
    unittest.main()
