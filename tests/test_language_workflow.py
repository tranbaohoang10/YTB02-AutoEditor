import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import latest_final_video_path, reserve_final_video_path


ROOT = Path(__file__).resolve().parents[1]


class LanguageWorkflowTests(unittest.TestCase):
    def test_permanent_english_script_contract(self) -> None:
        script = json.loads((ROOT / "input/script.en.json").read_text(encoding="utf-8"))
        self.assertEqual((script["language"], script["voice"], script["speed"]),
                         ("en", "am_eric", 1.0))
        self.assertEqual(len(script["scenes"]), 30)

    def test_permanent_vietnamese_script_contract(self) -> None:
        script = json.loads((ROOT / "input/script.vi.json").read_text(encoding="utf-8"))
        self.assertEqual((script["language"], script["voice"], script["speed"]),
                         ("vi", "hung_thinh", 1.0))
        self.assertEqual(len(script["scenes"]), 30)

    def test_entrypoints_map_to_their_permanent_scripts(self) -> None:
        en = (ROOT / "RUN_EN.bat").read_text(encoding="utf-8")
        vi = (ROOT / "RUN_VI.bat").read_text(encoding="utf-8")
        self.assertIn("--script input\\script.en.json --build", en)
        self.assertIn("--script input\\script.vi.json --build", vi)
        self.assertNotIn("script.vi.json", en)
        self.assertNotIn("script.en.json", vi)

    def test_output_numbering_is_independent_max_plus_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "FINAL_VIDEO_EN_2.mp4").write_bytes(b"en")
            (root / "FINAL_VIDEO_EN_7.mp4").write_bytes(b"en")
            (root / "FINAL_VIDEO_VI_3.mp4").write_bytes(b"vi")
            self.assertEqual(
                reserve_final_video_path(root, "en").name, "FINAL_VIDEO_EN_8.mp4"
            )
            self.assertEqual(
                reserve_final_video_path(root, "vi").name, "FINAL_VIDEO_VI_4.mp4"
            )

    def test_language_numbering_accepts_only_exact_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "FINAL_VIDEO_EN_9.MP4", "FINAL_VIDEO_en_9.mp4",
                "prefix_FINAL_VIDEO_EN_9.mp4", "FINAL_VIDEO_EN_x.mp4",
                "FINAL_VIDEO_VI_99.mp4",
            ):
                (root / name).write_bytes(b"ignore")
            self.assertEqual(
                reserve_final_video_path(root, "en").name, "FINAL_VIDEO_EN_1.mp4"
            )

    def test_latest_output_can_be_selected_per_language(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "FINAL_VIDEO_EN_4.mp4").write_bytes(b"en")
            (root / "FINAL_VIDEO_VI_8.mp4").write_bytes(b"vi")
            self.assertEqual(latest_final_video_path(root, "en").name,
                             "FINAL_VIDEO_EN_4.mp4")
            self.assertEqual(latest_final_video_path(root, "vi").name,
                             "FINAL_VIDEO_VI_8.mp4")


if __name__ == "__main__":
    unittest.main()
