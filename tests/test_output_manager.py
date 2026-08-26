import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import load_config
from src.models import AutoEditorError, Scene, Script
from src.output_manager import publish_output, reserve_output, safe_topic_slug


ROOT = Path(__file__).resolve().parents[1]


def _script(topic: str = "Black Wednesday", language: str = "en", part: int = 1) -> Script:
    return Script(
        "Title", language, "am_eric", 1.0, (Scene(1, "scene.mp4", "Text"),),
        topic=topic, part=part,
    )


class OutputManagerTests(unittest.TestCase):
    def test_windows_slug_rejects_absolute_unc_and_traversal(self) -> None:
        for unsafe in (
            r"C:\video", r"\\server\share", "../video", "a/../b", "CON.txt",
        ):
            with self.subTest(unsafe=unsafe), self.assertRaises(AutoEditorError):
                safe_topic_slug(unsafe)
        self.assertEqual(safe_topic_slug("Black: Wednesday?"), "Black_Wednesday")

    def test_numbering_is_scoped_by_topic_part_and_language(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = reserve_output(root, _script())
            second = reserve_output(root, _script())
            vi = reserve_output(root, _script(language="vi"))
            part_two = reserve_output(root, _script(part=2))
        self.assertEqual((first.number, second.number, vi.number, part_two.number), (1, 2, 1, 1))
        self.assertEqual(first.final_path.parts[-4:], ("Black_Wednesday", "Part_01", "EN", "Black_Wednesday_Part_01_EN_1.mp4"))

    def test_publish_validates_before_atomic_replace_and_writes_metadata(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory:
            reservation = reserve_output(Path(directory), _script())
            reservation.temporary_path.write_bytes(b"valid media placeholder")
            with patch(
                "src.output_manager.validate_final_media",
                return_value={"duration": 12.5, "checks": {"all": True}},
            ):
                metadata = publish_output(reservation, _script(), config)
            self.assertEqual(reservation.final_path.read_bytes(), b"valid media placeholder")
            self.assertTrue(reservation.metadata_path.is_file())
            self.assertEqual(metadata["duration"], 12.5)

    def test_failed_validation_keeps_empty_reservation(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory:
            reservation = reserve_output(Path(directory), _script())
            reservation.temporary_path.write_bytes(b"bad")
            with patch(
                "src.output_manager.validate_final_media",
                side_effect=AutoEditorError("bad media"),
            ), self.assertRaisesRegex(AutoEditorError, "bad media"):
                publish_output(reservation, _script(), config)
            self.assertEqual(reservation.final_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
