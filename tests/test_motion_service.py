import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import load_config
from src.models import AutoEditorError, Scene
from src.motion_service import render_image_motion
from src.motion_providers.ai_image_to_video import GeminiImageToVideoProvider, create_ai_motion_provider


ROOT = Path(__file__).resolve().parents[1]


class FakeAI:
    name = "fake_ai"
    def generate(self, image_path, output_path, duration, prompt, metadata):
        output_path.touch()


class FailingAI:
    name = "failing_ai"
    def generate(self, *args, **kwargs):
        raise AutoEditorError("AI failed")


class MotionServiceTests(unittest.TestCase):
    def test_gemini_ai_provider_requires_key_and_factory_is_explicit(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(AutoEditorError, "GEMINI_API_KEY"):
                GeminiImageToVideoProvider("veo")
            self.assertEqual(create_ai_motion_provider(None, "veo").name, "unconfigured_ai")

    def test_ai_provider_mocked_and_normalized(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.motion_service.probe_video", return_value={"duration": 1.0}
        ), patch("src.motion_service.prepare_video_scene") as normalize:
            root = Path(directory)
            destination = root / "scene.mp4"
            normalized = root / "scene.normalized.mp4"
            normalized.touch()
            render_image_motion(Scene(1, None, "Text"), root / "image.png", destination, 1.0, config, "ai", ai_provider=FakeAI())
        normalize.assert_called_once()

    def test_ai_failure_falls_back_only_when_configured(self) -> None:
        config = load_config(ROOT / "config.json")
        scene = Scene(1, None, "Text")
        with tempfile.TemporaryDirectory() as directory, patch("src.motion_service.prepare_image_scene") as local:
            root = Path(directory)
            render_image_motion(scene, root / "i.png", root / "o.mp4", 1.0, config, "ai", ai_provider=FailingAI(), fallback_local=True)
            local.assert_called_once()
            with self.assertRaisesRegex(AutoEditorError, "AI failed"):
                render_image_motion(scene, root / "i.png", root / "o.mp4", 1.0, config, "ai", ai_provider=FailingAI(), fallback_local=False)
