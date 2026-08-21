import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import load_config
from src.image_motion import MOTION_PRESETS, automatic_motion, prepare_image_scene


ROOT = Path(__file__).resolve().parents[1]


class ImageMotionTests(unittest.TestCase):
    def test_auto_motion_is_deterministic(self) -> None:
        self.assertEqual([automatic_motion(i) for i in range(1, 5)], [
            "slow_push_in", "pan_right", "slow_pull_out", "pan_left",
        ])
        self.assertEqual(automatic_motion(1), automatic_motion(1))

    def test_local_motion_command_has_output_contract_and_audio_duration(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.image_motion.run_media_command"
        ) as run:
            root = Path(directory)
            prepare_image_scene(root / "image.png", root / "scene.mp4", 6.27, config, "slow_push_in", validate_output=False)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("-t") + 1], "6.270000")
        self.assertEqual(command[command.index("-r") + 1], "30")
        self.assertEqual(command[command.index("-pix_fmt") + 1], "yuv420p")
        self.assertEqual(command[command.index("-c:v") + 1], "libx264")
        self.assertIn("s=1920x1080:fps=30", command[command.index("-vf") + 1])

    def test_all_local_presets_build_commands(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for preset in MOTION_PRESETS:
                with self.subTest(preset=preset), patch("src.image_motion.run_media_command"):
                    prepare_image_scene(root / "i.png", root / "o.mp4", 1.0, config, preset, validate_output=False)
