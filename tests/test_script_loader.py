import json
import tempfile
import unittest
from pathlib import Path

from src.models import AutoEditorError
from src.script_loader import load_script


class ScriptLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.videos = self.root / "videos"
        self.videos.mkdir()
        (self.videos / "one.mp4").touch()
        (self.videos / "two.mp4").touch()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, data: object) -> Path:
        path = self.root / "script.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def valid_data(self) -> dict:
        return {
            "title": "Test", "language": "en", "voice": "am_eric", "speed": 1.0,
            "scenes": [
                {"id": 2, "video": "two.mp4", "text": "Second."},
                {"id": 1, "video": "one.mp4", "text": "First."},
            ],
        }

    def test_valid_script_parsing_and_id_order(self) -> None:
        script = load_script(self.write(self.valid_data()), self.videos)
        self.assertEqual([scene.id for scene in script.scenes], [1, 2])
        self.assertEqual(script.language, "en")

    def test_default_speed_is_1_08_when_omitted(self) -> None:
        data = self.valid_data()
        del data["speed"]
        script = load_script(self.write(data), self.videos)
        self.assertEqual(script.speed, 1.08)

    def test_explicit_speed_overrides_default(self) -> None:
        for speed in (1.0, 1.15):
            with self.subTest(speed=speed):
                data = self.valid_data()
                data["speed"] = speed
                script = load_script(self.write(data), self.videos)
                self.assertEqual(script.speed, speed)

    def test_invalid_json(self) -> None:
        path = self.root / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(AutoEditorError, "JSON không hợp lệ"):
            load_script(path, self.videos)

    def test_duplicate_scene_id(self) -> None:
        data = self.valid_data()
        data["scenes"][0]["id"] = 1
        with self.assertRaisesRegex(AutoEditorError, "bị trùng"):
            load_script(self.write(data), self.videos)

    def test_non_contiguous_scene_id(self) -> None:
        data = self.valid_data()
        data["scenes"][0]["id"] = 3
        with self.assertRaisesRegex(AutoEditorError, "liên tục"):
            load_script(self.write(data), self.videos)

    def test_missing_video(self) -> None:
        data = self.valid_data()
        data["scenes"][0]["video"] = "missing.mp4"
        with self.assertRaisesRegex(AutoEditorError, "không tìm thấy video"):
            load_script(self.write(data), self.videos)


if __name__ == "__main__":
    unittest.main()
