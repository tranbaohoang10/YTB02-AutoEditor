import io
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from src.config import load_config
from src.image_assets import VisualAsset
from src.models import AutoEditorError, Scene, Script, TimelineEntry, VisualSettings
from src.pipeline import (
    _collect_source_audio_clips,
    _parser,
    atomic_replace_final,
    latest_final_video_path,
    main,
    reserve_final_video_path,
    run_pipeline,
)


class CLIContractTests(unittest.TestCase):
    def test_cli_accepts_new_actions_and_motion_mode(self) -> None:
        args = _parser().parse_args(["--generate-images", "--force-images", "--motion-mode", "local"])
        self.assertTrue(args.generate_images)
        self.assertTrue(args.force_images)
        self.assertEqual(args.motion_mode, "local")
        self.assertTrue(_parser().parse_args(["--build"]).build)
        self.assertTrue(_parser().parse_args(["--run-all"]).run_all)

    def test_dry_run_does_not_invoke_image_provider(self) -> None:
        with patch("src.pipeline.run_pipeline", return_value=None) as run:
            self.assertEqual(main(["--dry-run"]), 0)
        self.assertTrue(run.call_args.args[2])

    def test_real_run_pipeline_dry_run_does_not_resolve_or_generate(self) -> None:
        script = Script("Dry", "en", "am_eric", 1.08, (Scene(1, "x.mp4", "Text"),))
        with patch("src.pipeline.load_script", return_value=script), patch(
            "src.pipeline.resolve_visual_assets"
        ) as resolve, patch("src.pipeline.generate_narration") as tts, patch(
            "src.pipeline._display_dry_run"
        ):
            run_pipeline(Path("script.json"), Path(__file__).resolve().parents[1] / "config.json", True)
        resolve.assert_not_called()
        tts.assert_not_called()

    def test_main_prints_absolute_final_video_path(self) -> None:
        final = Path("output/FINAL_VIDEO_5.mp4")
        stdout = io.StringIO()
        with patch("src.pipeline.run_pipeline", return_value=final), redirect_stdout(stdout):
            self.assertEqual(main(["--build"]), 0)
        self.assertIn(f"FINAL VIDEO:\n{final.resolve()}", stdout.getvalue())

    def test_gemini_dry_run_missing_key_is_explicit_without_api_call(self) -> None:
        script = Script(
            "Dry", "en", "am_eric", 1.08,
            (Scene(1, None, "Text", visual_hint="Hint"),),
            VisualSettings(image_provider="gemini_api"),
        )
        with patch.dict(os.environ, {}, clear=True), patch("src.pipeline.load_script", return_value=script), patch(
            "src.pipeline.resolve_visual_assets"
        ) as resolve:
            with self.assertRaisesRegex(AutoEditorError, "GEMINI_API_KEY"):
                run_pipeline(Path("script.json"), Path(__file__).resolve().parents[1] / "config.json", True)
        resolve.assert_not_called()

    def test_source_audio_collection_skips_silent_video_and_does_not_loop_short_audio(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = load_config(root / "config.json")
        first = Scene(1, "with.mp4", "First")
        second = Scene(2, "silent.mp4", "Second")
        timeline = (
            TimelineEntry(first, Path("first.wav"), 2.0, 0.0, 2.0),
            TimelineEntry(second, Path("second.wav"), 2.0, 2.0, 4.0),
        )
        assets = {
            1: VisualAsset("video", Path("with.mp4")),
            2: VisualAsset("video", Path("silent.mp4")),
        }
        with patch("src.pipeline.probe_audio_duration", side_effect=(0.6, None)):
            clips = _collect_source_audio_clips(timeline, assets, config)
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0].start, 0.0)
        self.assertEqual(clips[0].duration, 0.6)

    def test_numbered_final_starts_at_one_for_empty_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                reserve_final_video_path(Path(directory)).name,
                "FINAL_VIDEO_1.mp4",
            )

    def test_numbered_final_increments_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "FINAL_VIDEO_1.mp4").write_bytes(b"old")
            self.assertEqual(reserve_final_video_path(root).name, "FINAL_VIDEO_2.mp4")

    def test_numbered_final_increments_contiguous_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for number in (1, 2, 3):
                (root / f"FINAL_VIDEO_{number}.mp4").write_bytes(b"old")
            self.assertEqual(reserve_final_video_path(root).name, "FINAL_VIDEO_4.mp4")

    def test_numbered_final_uses_max_instead_of_filling_gap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for number in (1, 4):
                (root / f"FINAL_VIDEO_{number}.mp4").write_bytes(b"old")
            self.assertEqual(reserve_final_video_path(root).name, "FINAL_VIDEO_5.mp4")

    def test_numbered_final_ignores_nonmatching_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "FINAL_VIDEO_backup.mp4",
                "FINAL_VIDEO_test.mp4",
                "abc.mp4",
                "FINAL_VIDEO_9.MP4",
                "prefix_FINAL_VIDEO_8.mp4",
            ):
                (root / name).write_bytes(b"unrelated")
            (root / "FINAL_VIDEO_3.mp4").mkdir()
            self.assertEqual(reserve_final_video_path(root).name, "FINAL_VIDEO_1.mp4")

    def test_concurrent_reservations_do_not_collide(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with ThreadPoolExecutor(max_workers=2) as executor:
                names = {
                    path.name
                    for path in executor.map(reserve_final_video_path, (root, root))
                }
            self.assertEqual(names, {"FINAL_VIDEO_1.mp4", "FINAL_VIDEO_2.mp4"})

    def test_latest_numbered_final_uses_exact_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "FINAL_VIDEO_2.mp4").write_bytes(b"old")
            (root / "FINAL_VIDEO_backup.mp4").write_bytes(b"ignore")
            self.assertEqual(latest_final_video_path(root).name, "FINAL_VIDEO_2.mp4")

    def test_atomic_final_publish_requires_owned_empty_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            final = root / "FINAL_VIDEO_1.mp4"
            temporary = root / "FINAL_VIDEO_1.building.mp4"
            final.touch()
            temporary.touch()
            with self.assertRaisesRegex(AutoEditorError, "không tạo được"):
                atomic_replace_final(temporary, final)
            temporary.write_bytes(b"new")
            atomic_replace_final(temporary, final)
            self.assertEqual(final.read_bytes(), b"new")

            next_temporary = root / "FINAL_VIDEO_2.building.mp4"
            next_temporary.write_bytes(b"newer")
            with self.assertRaisesRegex(AutoEditorError, "không còn được giữ"):
                atomic_replace_final(next_temporary, final)
            self.assertEqual(final.read_bytes(), b"new")
