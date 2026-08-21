from __future__ import annotations

from pathlib import Path

from .config import AppConfig
from .image_motion import automatic_motion, prepare_image_scene
from .media_qc import probe_video
from .models import AutoEditorError, Scene
from .motion_providers.ai_image_to_video import PRESERVATION_PROMPT, UnconfiguredAIMotionProvider
from .motion_providers.base import MotionProvider
from .video_builder import prepare_video_scene


def render_image_motion(
    scene: Scene,
    image_path: Path,
    destination: Path,
    duration: float,
    config: AppConfig,
    mode: str,
    *,
    ai_provider: MotionProvider | None = None,
    fallback_local: bool = False,
) -> None:
    resolved_mode = "local" if mode == "auto" else mode
    preset = automatic_motion(scene.id) if scene.motion_type == "auto" else scene.motion_type
    if resolved_mode == "local":
        prepare_image_scene(image_path, destination, duration, config, preset)
        return
    if resolved_mode != "ai":
        raise AutoEditorError(f"Motion mode không hỗ trợ: {mode}")
    active = ai_provider or UnconfiguredAIMotionProvider()
    try:
        active.generate(
            image_path, destination, duration, PRESERVATION_PROMPT,
            {"scene_id": scene.id, "preserve_original": True},
        )
        probe_video(destination, config.ffprobe)
        normalized = destination.with_name(f"{destination.stem}.normalized.mp4")
        prepare_video_scene(destination, normalized, duration, config)
        normalized.replace(destination)
    except AutoEditorError:
        if not fallback_local:
            raise
        prepare_image_scene(image_path, destination, duration, config, preset)
