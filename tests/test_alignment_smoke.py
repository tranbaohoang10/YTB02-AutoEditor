import tempfile
import unittest
import wave
from pathlib import Path

from src.alignment_smoke import wav_duration
from src.models import AutoEditorError


class AlignmentSmokeTests(unittest.TestCase):
    def test_wav_duration_uses_real_pcm_frames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "short.wav"
            with wave.open(str(path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(24000)
                wav_file.writeframes(b"\x00\x00" * 12000)
            self.assertAlmostEqual(wav_duration(path), 0.5)

    def test_missing_wav_is_clear_error(self) -> None:
        with self.assertRaisesRegex(AutoEditorError, "Không đọc được WAV"):
            wav_duration(Path("definitely-missing.wav"))


if __name__ == "__main__":
    unittest.main()
