import json
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from tools.analyze_narration_pacing import analyze


def _write_wav(path: Path, samples: list[int], sample_rate: int = 24000) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(struct.pack(f"<{len(samples)}h", *samples))


class PacingAnalyzerTests(unittest.TestCase):
    def test_pcm_summary_and_buckets_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "voice.wav"
            samples = [9000] * 2400 + [0] * 4800 + [9000] * 2400
            _write_wav(path, samples)
            result = analyze(path, threshold_db=-35.0, minimum_ms=120)
        self.assertEqual(result["silence_count"], 1)
        self.assertAlmostEqual(result["pcm_pause_summary"]["maximum"], 0.2)
        self.assertEqual(result["pause_buckets"]["medium_180_300ms"], 1)

    def test_alignment_diagnostics_produce_scene_boundary_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav = root / "voice.wav"
            _write_wav(wav, [9000] * 24000)
            alignment = root / "alignment"
            alignment.mkdir()
            rows = (
                {
                    "scene_id": 1, "audio_duration": 0.5,
                    "timeline_start": 0.0, "timeline_end": 0.5,
                    "words": [{"word": "One.", "start": 0.0, "end": 0.35}],
                },
                {
                    "scene_id": 2, "audio_duration": 0.5,
                    "timeline_start": 0.5, "timeline_end": 1.0,
                    "words": [{"word": "Two.", "start": 0.0, "end": 0.4}],
                },
            )
            for index, row in enumerate(rows, 1):
                (alignment / f"scene_{index:03d}.json").write_text(
                    json.dumps(row), encoding="utf-8"
                )
            result = analyze(wav, alignment_dir=alignment)
        self.assertEqual(result["scene_boundary_summary"]["count"], 1)
        self.assertAlmostEqual(result["scene_boundary_summary"]["maximum"], 0.15)


if __name__ == "__main__":
    unittest.main()
