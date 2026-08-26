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

    def test_watermark_and_pause_aware_transition_defaults(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = load_config(root / "config.json")
        self.assertTrue(config.watermark.enabled)
        self.assertEqual(config.watermark.text, "l0ki")
        self.assertEqual(config.watermark.position, "bottom_right")
        self.assertEqual(config.watermark.opacity, 0.86)
        self.assertEqual((config.watermark.margin_right, config.watermark.margin_bottom),
                         (58, 50))
        self.assertEqual(config.watermark.border_width, 1)
        self.assertTrue(config.source_cleanup.enabled)
        self.assertEqual(config.source_cleanup.strategy, "paper_corner_patch")
        self.assertTrue(config.visual_quality.enabled)
        self.assertEqual(config.subtitles.font_size, 56)
        self.assertTrue(config.subtitles.bold)
        self.assertEqual(config.subtitles.shadow, 0)
        self.assertTrue(config.transitions.pause_aware)
        self.assertEqual(config.transitions.minimum_pause_ms, 250)
        self.assertEqual(config.transitions.preferred_trigger_ms, 300)
        self.assertEqual(config.transitions.max_transition_ms, 350)
        self.assertEqual(config.transitions.sfx_gain_db, -21.5)


if __name__ == "__main__":
    unittest.main()
