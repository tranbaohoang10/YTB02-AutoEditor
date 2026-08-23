import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.ffmpeg_utils import probe_audio_duration


class FFmpegUtilsTests(unittest.TestCase):
    def test_probe_audio_duration_returns_none_without_audio_stream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "silent.mp4"
            media.write_bytes(b"media")
            result = Mock(returncode=0, stdout=json.dumps({"streams": [], "format": {}}))
            with patch("src.ffmpeg_utils.subprocess.run", return_value=result):
                self.assertIsNone(probe_audio_duration(media, "ffprobe"))

    def test_probe_audio_duration_prefers_stream_duration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "with-audio.mp4"
            media.write_bytes(b"media")
            result = Mock(
                returncode=0,
                stdout=json.dumps({
                    "streams": [{"duration": "1.250"}],
                    "format": {"duration": "4.000"},
                }),
            )
            with patch("src.ffmpeg_utils.subprocess.run", return_value=result):
                self.assertEqual(probe_audio_duration(media, "ffprobe"), 1.25)


if __name__ == "__main__":
    unittest.main()
