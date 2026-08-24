import unittest
from pathlib import Path

from src.config import load_config


class ConfigTests(unittest.TestCase):
    def test_alignment_defaults_are_strict_cpu_whisperx(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = load_config(root / "config.json")
        self.assertEqual(config.alignment.engine, "whisperx")
        self.assertEqual(config.alignment.device, "cpu")
        self.assertFalse(config.alignment.allow_approximate_fallback)
        self.assertEqual(config.alignment.cache_dir, (root / ".cache" / "alignment").resolve())
        self.assertIsNone(config.alignment.model_en)
        self.assertEqual(
            config.alignment.model_vi, "dragonSwing/wav2vec2-base-vietnamese"
        )

    def test_loudness_config_defaults_are_parsed(self) -> None:
        root = Path(__file__).resolve().parents[1]
        audio = load_config(root / "config.json").audio
        self.assertTrue(audio.normalize_loudness)
        self.assertEqual(audio.target_lufs, -18.0)
        self.assertEqual(audio.true_peak_db, -1.5)
        self.assertEqual(audio.lra, 7.0)
        self.assertEqual(audio.gap_ms, 0)
        self.assertEqual(audio.narration_edge_silence_ms, 50)
        self.assertEqual(audio.mix_sample_rate, 48000)
        self.assertTrue(audio.preserve_source_audio)
        self.assertEqual(audio.source_audio_gain_db, -18.0)
        self.assertEqual(audio.source_audio_fade_ms, 120)
        self.assertTrue(audio.smart_pause_compression)
        self.assertEqual(audio.pause_threshold_db, -35.0)
        self.assertEqual(audio.pause_min_detect_ms, 120)
        self.assertEqual(audio.pause_medium_target_ms, 220)
        self.assertEqual(audio.pause_long_target_ms, 280)
        self.assertEqual(audio.pause_very_long_target_ms, 350)
        self.assertEqual(audio.pause_profiles["en"].sentence_target_ms, 320)
        self.assertEqual(audio.pause_profiles["en"].chunk_join_ms, 320)
        self.assertEqual(audio.pause_profiles["vi"].sentence_target_ms, 350)
        self.assertEqual(audio.pause_profiles["vi"].chunk_join_ms, 380)
        self.assertEqual(audio.pause_edge_guard_ms, 25)
        self.assertEqual(audio.pause_crossfade_ms, 8)
        self.assertEqual(audio.narration_mode, "continuous")
        self.assertEqual(audio.continuous_chunk_scenes, 5)
        self.assertEqual(audio.scene_tail_ms, 100)


if __name__ == "__main__":
    unittest.main()
