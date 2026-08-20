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
        self.assertIsNone(config.alignment.model_vi)

    def test_loudness_config_defaults_are_parsed(self) -> None:
        root = Path(__file__).resolve().parents[1]
        audio = load_config(root / "config.json").audio
        self.assertTrue(audio.normalize_loudness)
        self.assertEqual(audio.target_lufs, -18.0)
        self.assertEqual(audio.true_peak_db, -1.5)
        self.assertEqual(audio.lra, 7.0)


if __name__ == "__main__":
    unittest.main()
