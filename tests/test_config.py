import unittest
from pathlib import Path

from PIL import Image

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
        self.assertEqual(config.watermark.position, "bottom_right")
        self.assertEqual(
            config.watermark.logo_file,
            root / "assets" / "branding" / "l0ki_archives_logo.png",
        )
        self.assertTrue(config.watermark.logo_file.is_file())
        self.assertEqual(config.watermark.logo_width, 76)
        self.assertEqual(config.watermark.logo_opacity, 0.64)
        self.assertLessEqual(
            config.watermark.logo_width, round(config.video.width * 0.04)
        )
        with Image.open(config.watermark.logo_file) as logo:
            self.assertEqual((logo.mode, logo.size), ("RGBA", (1254, 1254)))
            self.assertEqual(logo.getchannel("A").getextrema(), (0, 255))
        self.assertEqual((config.watermark.margin_right, config.watermark.margin_bottom),
                         (20, 20))
        self.assertEqual((config.watermark.shadow_x, config.watermark.shadow_y), (1, 1))
        self.assertEqual(config.watermark.shadow_opacity, 0.16)
        self.assertEqual(config.watermark.shadow_blur, 0.45)
        self.assertTrue(config.source_cleanup.enabled)
        self.assertEqual(
            config.source_cleanup.strategy, "cover_with_official_logo"
        )
        self.assertEqual(config.source_cleanup.cover_logo_width, 110)
        self.assertEqual(config.source_cleanup.cover_logo_opacity, 0.42)
        self.assertEqual(
            (config.source_cleanup.cover_margin_right,
             config.source_cleanup.cover_margin_bottom),
            (14, 14),
        )
        self.assertEqual(
            (config.source_cleanup.cover_nudge_left,
             config.source_cleanup.cover_nudge_up),
            (111, 112),
        )
        self.assertEqual(
            (config.source_cleanup.median_radius, config.source_cleanup.feather_px),
            (30, 3),
        )
        self.assertTrue(config.visual_quality.enabled)
        self.assertEqual(config.subtitles.font_size, 56)
        self.assertTrue(config.subtitles.bold)
        self.assertEqual(config.subtitles.shadow, 0)
        self.assertTrue(config.transitions.pause_aware)
        self.assertEqual(config.transitions.minimum_pause_ms, 250)
        self.assertEqual(config.transitions.preferred_trigger_ms, 300)
        self.assertEqual(config.transitions.max_transition_ms, 350)
        self.assertEqual(config.transitions.sfx_gain_db, -21.5)

    def test_official_branding_directory_contains_no_generated_logo(self) -> None:
        root = Path(__file__).resolve().parents[1]
        branding = root / "assets" / "branding"
        self.assertEqual(
            sorted(path.name for path in branding.glob("*.png")),
            ["l0ki_archives_logo.png"],
        )


if __name__ == "__main__":
    unittest.main()
