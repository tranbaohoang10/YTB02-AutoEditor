import os
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from PIL import Image

from src.config import load_config
from src.image_motion import prepare_image_scene
from src.layered_composer import render_layered_scene
from src.layered_manifest import SceneTransition, load_layered_manifest
from src.media_qc import probe_video
from src.video_builder import concat_video_scenes_with_transitions


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("YTB_RUN_REAL_MEDIA") == "1", "real FFmpeg smoke is opt-in")
class RealMediaSmokeTests(unittest.TestCase):
    def test_jpeg_to_limited_yuv420p_local_motion_real_ffmpeg(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        self.assertIsNotNone(ffmpeg)
        self.assertIsNotNone(ffprobe)
        config = load_config(ROOT / "config.json")
        config = replace(config, ffmpeg=ffmpeg, ffprobe=ffprobe)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "source.jpeg"
            output = root / "motion.mp4"
            Image.new("RGB", (1280, 720), "#d9d1bd").save(image, format="JPEG", quality=92)
            prepare_image_scene(image, output, 2.4, config, "slow_push_in")
            info = probe_video(output, ffprobe)
        self.assertEqual((info["width"], info["height"]), (1920, 1080))
        self.assertEqual(info["codec_name"], "h264")
        self.assertEqual(info["pix_fmt"], "yuv420p")
        self.assertEqual(info["color_range"], "tv")
        self.assertEqual(info["r_frame_rate"], "30/1")
        self.assertLessEqual(abs(info["duration"] - 2.4), 1 / 30 + 0.01)

    def test_real_layered_scene_and_two_scene_transition(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        self.assertIsNotNone(ffmpeg)
        self.assertIsNotNone(ffprobe)
        config = load_config(ROOT / "config.json")
        config = replace(config, ffmpeg=ffmpeg, ffprobe=ffprobe)
        manifest = load_layered_manifest(
            ROOT / "input" / "sample-scenes" / "scene_01",
            expected_width=1920, expected_height=1080,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "layered_1.mp4"
            second = root / "layered_2.mp4"
            final = root / "two_scenes.mp4"
            render_layered_scene(manifest, first, 3.0, config)
            render_layered_scene(manifest, second, 3.0, config)
            concat_video_scenes_with_transitions(
                (first, second), (3.0, 3.0),
                (SceneTransition("paper_wipe", 0.45),), final, config,
            )
            one = probe_video(first, ffprobe)
            two = probe_video(final, ffprobe)
        for info in (one, two):
            self.assertEqual((info["width"], info["height"]), (1920, 1080))
            self.assertEqual(info["codec_name"], "h264")
            self.assertEqual(info["pix_fmt"], "yuv420p")
            self.assertEqual(info["color_range"], "tv")
            self.assertEqual(info["r_frame_rate"], "30/1")
        self.assertLessEqual(abs(one["duration"] - 3.0), 1 / 30 + 0.01)
        self.assertLessEqual(abs(two["duration"] - 6.0), 1 / 30 + 0.02)


if __name__ == "__main__":
    unittest.main()
