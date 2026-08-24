import math
import struct
import tempfile
import unittest
import wave
from dataclasses import replace
from pathlib import Path

from src.config import load_config
from src.narration import compress_smart_pauses, detect_pause_regions


ROOT = Path(__file__).resolve().parents[1]


def _tone(sample_rate: int, milliseconds: int, amplitude: int = 9000) -> list[int]:
    count = round(sample_rate * milliseconds / 1000)
    return [
        round(amplitude * math.sin(2 * math.pi * 220 * index / sample_rate))
        for index in range(count)
    ]


def _write_wav(path: Path, samples: list[int], sample_rate: int = 24000) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _duration(path: Path) -> float:
    with wave.open(str(path), "rb") as source:
        return source.getnframes() / source.getframerate()


class SmartPauseCompressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audio = load_config(ROOT / "config.json").audio
        self.sample_rate = self.audio.sample_rate

    def _compress_known_pause(self, pause_ms: int):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.wav"
            samples = [
                *_tone(self.sample_rate, 200),
                *([0] * round(self.sample_rate * pause_ms / 1000)),
                *_tone(self.sample_rate, 200),
            ]
            _write_wav(path, samples, self.sample_rate)
            before = _duration(path)
            report = compress_smart_pauses(path, self.audio)
            after = _duration(path)
        return before, after, report

    def test_100ms_pause_is_unchanged(self) -> None:
        before, after, report = self._compress_known_pause(100)
        self.assertAlmostEqual(after, before, places=3)
        self.assertEqual(report.compressed_pause_count, 0)

    def test_250ms_pause_compresses_to_medium_target(self) -> None:
        before, after, report = self._compress_known_pause(250)
        self.assertAlmostEqual(before - after, 0.120, delta=0.012)
        self.assertAlmostEqual(report.edits[0].target_ms, 130, delta=10)

    def test_500ms_pause_compresses_to_long_target(self) -> None:
        before, after, report = self._compress_known_pause(500)
        self.assertAlmostEqual(before - after, 0.340, delta=0.012)
        self.assertAlmostEqual(report.edits[0].target_ms, 160, delta=10)

    def test_900ms_pause_compresses_to_very_long_target(self) -> None:
        before, after, report = self._compress_known_pause(900)
        self.assertAlmostEqual(before - after, 0.710, delta=0.012)
        self.assertAlmostEqual(report.edits[0].target_ms, 190, delta=10)

    def test_low_energy_phoneme_with_peak_above_threshold_is_not_silence(self) -> None:
        count = round(self.sample_rate * 0.25)
        low_energy = [600 if index % 4 == 0 else -600 if index % 4 == 2 else 0 for index in range(count)]
        regions = detect_pause_regions(
            low_energy, self.sample_rate, self.audio.pause_threshold_db,
            self.audio.pause_min_detect_ms,
        )
        self.assertEqual(regions, ())

    def test_edge_guards_preserve_speech_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guard.wav"
            left = _tone(self.sample_rate, 200)
            right = _tone(self.sample_rate, 200, 7000)
            _write_wav(path, [*left, *([0] * 12000), *right], self.sample_rate)
            compress_smart_pauses(path, self.audio)
            with wave.open(str(path), "rb") as source:
                frames = source.readframes(source.getnframes())
            result = list(struct.unpack(f"<{len(frames) // 2}h", frames))
        self.assertEqual(result[:len(left)], left)
        self.assertEqual(result[-len(right):], right)

    def test_crossfade_does_not_change_active_speech_duration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crossfade.wav"
            speech = [*_tone(self.sample_rate, 200), *_tone(self.sample_rate, 200)]
            samples = [*speech[:4800], *([0] * 12000), *speech[4800:]]
            _write_wav(path, samples, self.sample_rate)
            active_before = sum(value != 0 for value in samples)
            compress_smart_pauses(path, self.audio)
            with wave.open(str(path), "rb") as source:
                frames = source.readframes(source.getnframes())
            result = struct.unpack(f"<{len(frames) // 2}h", frames)
        self.assertEqual(sum(value != 0 for value in result), active_before)

    def test_disabled_policy_leaves_pause_untouched_through_config(self) -> None:
        disabled = replace(self.audio, smart_pause_compression=False)
        self.assertFalse(disabled.smart_pause_compression)


if __name__ == "__main__":
    unittest.main()
