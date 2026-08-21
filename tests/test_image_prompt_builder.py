import unittest

from src.image_prompt_builder import build_image_prompt, master_style_prompt
from src.models import Scene, Script, VisualSettings
from src.style_presets import PRESETS, get_style_preset


class ImagePromptBuilderTests(unittest.TestCase):
    def script(self) -> Script:
        return Script(
            "Test", "en", "am_eric", 1.08,
            (Scene(1, None, "Narration fallback.", visual_hint="Specific visual."),),
            VisualSettings(style_preset="newsprint-editorial"),
        )

    def test_prompt_is_deterministic_and_uses_visual_hint(self) -> None:
        script = self.script()
        first = build_image_prompt(script, script.scenes[0])
        self.assertEqual(first, build_image_prompt(script, script.scenes[0]))
        self.assertIn("Specific visual", first)
        self.assertIn("NO TEXT", first)

    def test_explicit_prompt_wins_over_hint(self) -> None:
        script = self.script()
        scene = Scene(1, None, "Narration", visual_hint="Hint", image_prompt="Exact subject")
        prompt = build_image_prompt(script, scene)
        self.assertIn("Exact subject", prompt)
        self.assertNotIn("Scene 001 subject: Hint", prompt)

    def test_all_required_style_presets_load(self) -> None:
        required = {
            "newsprint-editorial", "photo-collage", "modern-flat",
            "american-retro", "documentary-paper-collage",
        }
        self.assertTrue(required.issubset(PRESETS))
        self.assertIn("Palette:", get_style_preset("newsprint-editorial").prompt())
        self.assertIn("consistent visual language", master_style_prompt(self.script()))
