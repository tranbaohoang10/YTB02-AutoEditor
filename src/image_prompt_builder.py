from __future__ import annotations

from .models import Scene, Script
from .style_presets import get_style_preset


def master_style_prompt(script: Script) -> str:
    preset = get_style_preset(script.visual.style_preset)
    return (
        f"Create one {script.visual.aspect_ratio} documentary editorial image with a consistent visual language. "
        f"{preset.prompt()} Preserve factual visual coherence. NO TEXT, no captions, no logos, "
        "no watermarks, and no UI. The video pipeline adds all readable text later."
    )


def build_image_prompt(script: Script, scene: Scene) -> str:
    content = scene.image_prompt or scene.visual_hint or scene.text
    return (
        f"{master_style_prompt(script)}\n"
        f"Scene {scene.id:03d} subject: {content.strip()}\n"
        "Single coherent composition; avoid grids and multiple unrelated panels."
    )


def build_retry_prompt(prompt: str) -> str:
    return (
        f"{prompt}\nSimplify the composition to one clear subject and a restrained background. "
        "No text, symbols, labels, brands, or complex small details."
    )
