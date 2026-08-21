import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.config import load_config
from src.video_builder import concat_audio_scenes, prepare_video_scene


ROOT = Path(__file__).resolve().parents[1]


class VideoBuilderTests(unittest.TestCase):
    def test_prepare_video_scene_keeps_trim_freeze_and_video_only_contract(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ) as run:
            root = Path(directory)
            prepare_video_scene(root / "source.mp4", root / "prepared.mp4", 4.6, config)
        command = run.call_args.args[0]
        vf = command[command.index("-vf") + 1]
        self.assertIn("tpad=stop_mode=clone:stop_duration=4.600000", vf)
        self.assertIn("trim=duration=4.600000", vf)
        self.assertIn("force_original_aspect_ratio=decrease", vf)
        self.assertIn("-an", command)

    def test_concat_audio_uses_loudnorm_when_enabled(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ) as run:
            root = Path(directory)
            concat_audio_scenes((root / "scene.wav",), root / "voice.wav", config, root)
        command = run.call_args.args[0]
        filter_value = command[command.index("-af") + 1]
        self.assertEqual(filter_value, "loudnorm=I=-18.0:TP=-1.5:LRA=7.0")

    def test_concat_audio_skips_loudnorm_when_disabled(self) -> None:
        config = load_config(ROOT / "config.json")
        config = replace(
            config, audio=replace(config.audio, normalize_loudness=False)
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ) as run:
            root = Path(directory)
            concat_audio_scenes((root / "scene.wav",), root / "voice.wav", config, root)
        command = run.call_args.args[0]
        self.assertNotIn("-af", command)
        self.assertFalse(any("loudnorm" in item for item in command))


if __name__ == "__main__":
    unittest.main()
