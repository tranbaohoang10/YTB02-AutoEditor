import tempfile
import unittest
from pathlib import Path

from src.models import Scene, Script
from src.tts_bridge import build_narration_chunks


class NarrationChunkTests(unittest.TestCase):
    def test_scene_mode_preserves_one_file_per_scene(self) -> None:
        script = Script(
            "Test", "en", "am_eric", 1.08,
            tuple(Scene(index, f"{index}.mp4", f"Scene {index}.") for index in range(1, 4)),
        )
        with tempfile.TemporaryDirectory() as directory:
            chunks = build_narration_chunks(script, Path(directory), "scene", 5)
        self.assertEqual([item.scene_ids for item in chunks], [(1,), (2,), (3,)])
        self.assertEqual([item.output_path.name for item in chunks], [
            "scene_001.wav", "scene_002.wav", "scene_003.wav",
        ])

    def test_continuous_chunks_keep_exact_multi_scene_ownership(self) -> None:
        scenes = tuple(
            Scene(index, f"{index}.mp4", f"Canonical scene {index}.")
            for index in range(1, 8)
        )
        script = Script("Test", "en", "am_eric", 1.08, scenes)
        with tempfile.TemporaryDirectory() as directory:
            chunks = build_narration_chunks(script, Path(directory), "continuous", 3)
        self.assertEqual([item.scene_ids for item in chunks], [(1, 2, 3), (4, 5, 6), (7,)])
        self.assertEqual([item.output_path.name for item in chunks], [
            "chunk_001.wav", "chunk_002.wav", "chunk_003.wav",
        ])
        self.assertEqual(
            " ".join(item.text for item in chunks),
            " ".join(scene.text for scene in scenes),
        )


if __name__ == "__main__":
    unittest.main()
