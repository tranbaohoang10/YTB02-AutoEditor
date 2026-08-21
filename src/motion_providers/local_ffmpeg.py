from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..image_motion import prepare_image_scene


class LocalFFmpegMotionProvider:
    name = "local_ffmpeg"

    def __init__(self, config: AppConfig, preset: str) -> None:
        self.config = config
        self.preset = preset

    def generate(
        self, image_path: Path, output_path: Path, duration: float,
        prompt: str, metadata: dict[str, Any],
    ) -> None:
        prepare_image_scene(image_path, output_path, duration, self.config, self.preset)
