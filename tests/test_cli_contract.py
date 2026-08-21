import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.models import AutoEditorError, Scene, Script, VisualSettings
from src.pipeline import _parser, atomic_replace_final, main, run_pipeline


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

    def test_atomic_final_replacement_preserves_old_final_on_invalid_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            final = root / "FINAL_VIDEO.mp4"
            temporary = root / "FINAL_VIDEO.building.mp4"
            final.write_bytes(b"old")
            temporary.touch()
            with self.assertRaisesRegex(AutoEditorError, "không tạo được"):
                atomic_replace_final(temporary, final)
            self.assertEqual(final.read_bytes(), b"old")
            temporary.write_bytes(b"new")
            atomic_replace_final(temporary, final)
            self.assertEqual(final.read_bytes(), b"new")
