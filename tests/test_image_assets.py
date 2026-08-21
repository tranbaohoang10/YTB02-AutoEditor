import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.image_assets import prompt_hash, resolve_visual_assets
from src.image_providers.gemini_api import GeminiApiImageProvider
from src.models import AutoEditorError, Scene, Script, VisualSettings


class FakeProvider:
    name = "gemini_api"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt, output_path, aspect_ratio, image_size, metadata):
        self.calls += 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (800, 450), "navy").save(output_path)


class ImageAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.videos = self.root / "videos"
        self.images = self.root / "images"
        self.generated = self.root / "generated"
        self.videos.mkdir()
        self.images.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def generated_script(self) -> Script:
        return Script(
            "Generated", "en", "am_eric", 1.08,
            (Scene(1, None, "Narration", visual_hint="Historic bank"),),
            VisualSettings(image_provider="gemini_api", image_model="model-x"),
        )

    def test_prompt_hash_is_stable_and_sensitive(self) -> None:
        self.assertEqual(prompt_hash("p", "x", "m"), prompt_hash("p", "x", "m"))
        self.assertNotEqual(prompt_hash("p", "x", "m"), prompt_hash("q", "x", "m"))

    def test_existing_manual_image_passes_without_provider(self) -> None:
        Image.new("RGB", (800, 450), "white").save(self.images / "scene.png")
        script = Script("Manual", "en", "am_eric", 1.08, (Scene(1, None, "Text", image="scene.png"),))
        assets = resolve_visual_assets(script, self.videos, self.images, self.generated)
        self.assertEqual(assets[1].path, self.images / "scene.png")

    def test_generated_image_cache_skip_and_force(self) -> None:
        provider = FakeProvider()
        script = self.generated_script()
        resolve_visual_assets(script, self.videos, self.images, self.generated, provider=provider)
        resolve_visual_assets(script, self.videos, self.images, self.generated, provider=provider)
        self.assertEqual(provider.calls, 1)
        resolve_visual_assets(script, self.videos, self.images, self.generated, provider=provider, force=True)
        self.assertEqual(provider.calls, 2)

    def test_cache_metadata_has_no_secret(self) -> None:
        provider = FakeProvider()
        resolve_visual_assets(self.generated_script(), self.videos, self.images, self.generated, provider=provider)
        raw = (self.generated / "scene_001.json").read_text(encoding="utf-8")
        payload = json.loads(raw)
        self.assertNotIn("secret", raw.casefold())
        self.assertNotIn("api_key", raw.casefold())
        self.assertEqual(payload["provider"], "gemini_api")

    def test_manual_provider_missing_generated_asset_fails(self) -> None:
        script = Script(
            "Manual", "en", "am_eric", 1.08,
            (Scene(1, None, "Text", visual_hint="Hint"),),
        )
        with self.assertRaisesRegex(AutoEditorError, "Manual image provider"):
            resolve_visual_assets(script, self.videos, self.images, self.generated)

    def test_gemini_key_required_only_when_provider_constructed(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(AutoEditorError, "GEMINI_API_KEY"):
                GeminiApiImageProvider("model")

    def test_gemini_provider_mocked_generate_passes(self) -> None:
        provider = GeminiApiImageProvider("model", api_key="test-only", sleeper=lambda _: None)
        with patch.object(provider, "_generate_once") as generate:
            provider.generate("prompt", self.generated / "x.png", "16:9", "2K", {})
        generate.assert_called_once()

    def test_gemini_provider_retries_technical_error_with_bound(self) -> None:
        provider = GeminiApiImageProvider(
            "model", api_key="test-only", max_attempts=3, sleeper=lambda _: None
        )
        with patch.object(provider, "_generate_once", side_effect=[RuntimeError("temporary"), None]) as generate:
            provider.generate("prompt", self.generated / "x.png", "16:9", "2K", {})
        self.assertEqual(generate.call_count, 2)
