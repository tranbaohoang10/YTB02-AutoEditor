import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.media_qc import probe_video, validate_image
from src.models import AutoEditorError


class MediaQCTests(unittest.TestCase):
    def test_image_qc_accepts_decodable_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.png"
            Image.new("RGB", (800, 450), "white").save(path)
            self.assertEqual(validate_image(path), (800, 450))

    def test_image_qc_rejects_corrupt_and_tiny(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corrupt = root / "corrupt.png"
            corrupt.write_bytes(b"not image")
            with self.assertRaisesRegex(AutoEditorError, "corrupt"):
                validate_image(corrupt)
            tiny = root / "tiny.png"
            Image.new("RGB", (10, 10)).save(tiny)
            with self.assertRaisesRegex(AutoEditorError, "quá nhỏ"):
                validate_image(tiny)

    def test_video_qc_parses_valid_stream(self) -> None:
        payload = {"streams": [{"codec_name": "h264", "width": 1920, "height": 1080, "r_frame_rate": "30/1", "pix_fmt": "yuv420p"}], "format": {"duration": "2.0"}}
        result = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        with tempfile.TemporaryDirectory() as directory, patch("src.media_qc.subprocess.run", return_value=result):
            path = Path(directory) / "video.mp4"
            path.write_bytes(b"x")
            info = probe_video(path, "ffprobe")
        self.assertEqual(info["codec_name"], "h264")
        self.assertEqual(info["duration"], 2.0)
        self.assertEqual(info["fps"], 30.0)

    def test_video_qc_rejects_zero_fps(self) -> None:
        payload = {"streams": [{"codec_name": "h264", "width": 1920, "height": 1080, "r_frame_rate": "0/0"}], "format": {"duration": "2.0"}}
        result = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        with tempfile.TemporaryDirectory() as directory, patch("src.media_qc.subprocess.run", return_value=result):
            path = Path(directory) / "video.mp4"
            path.write_bytes(b"x")
            with self.assertRaisesRegex(AutoEditorError, "FPS"):
                probe_video(path, "ffprobe")
