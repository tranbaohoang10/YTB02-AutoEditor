import os
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from PIL import Image

from src.config import load_config
from src.image_motion import prepare_image_scene
from src.media_qc import probe_video


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


if __name__ == "__main__":
    unittest.main()
