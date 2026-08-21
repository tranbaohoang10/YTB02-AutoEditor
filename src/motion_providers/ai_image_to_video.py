from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable

from ..models import AutoEditorError


PRESERVATION_PROMPT = (
    "Subtle camera push-in, slight parallax, restrained motion. Preserve the original "
    "composition, characters, geometry, objects, logos and any existing text. No new objects, "
    "no redesign, no major geometry change."
)


class UnconfiguredAIMotionProvider:
    """Explicit boundary for future official/vendor adapters; never fakes remote output."""

    name = "unconfigured_ai"

    def generate(
        self, image_path: Path, output_path: Path, duration: float,
        prompt: str, metadata: dict[str, Any],
    ) -> None:
        raise AutoEditorError(
            "BLOCKED_EXTERNAL: AI image-to-video provider chưa được cấu hình. "
            "Dùng motion_mode=local hoặc cấu hình official provider adapter."
        )


class GeminiImageToVideoProvider:
    """Official Google GenAI/Veo adapter; instantiated only for explicit AI opt-in."""

    name = "gemini_image_to_video"

    def __init__(
        self, model: str, api_key: str | None = None,
        poll_seconds: float = 10.0, max_polls: int = 90,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = os.environ.get("GEMINI_VIDEO_MODEL") or model
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.poll_seconds = max(1.0, poll_seconds)
        self.max_polls = max(1, max_polls)
        self.sleeper = sleeper
        if not self.api_key:
            raise AutoEditorError(
                "BLOCKED_EXTERNAL: gemini_image_to_video cần GEMINI_API_KEY."
            )

    def generate(
        self, image_path: Path, output_path: Path, duration: float,
        prompt: str, metadata: dict[str, Any],
    ) -> None:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise AutoEditorError("Thiếu google-genai. Hãy chạy SETUP.bat.") from exc
        try:
            client = genai.Client(api_key=self.api_key)
            operation = client.models.generate_videos(
                model=self.model,
                prompt=f"{PRESERVATION_PROMPT} {prompt}",
                image=types.Image.from_file(location=str(image_path)),
                config=types.GenerateVideosConfig(aspect_ratio="16:9", number_of_videos=1),
            )
            for _ in range(self.max_polls):
                if getattr(operation, "done", False):
                    break
                self.sleeper(self.poll_seconds)
                operation = client.operations.get(operation)
            else:
                raise AutoEditorError("BLOCKED_EXTERNAL: AI image-to-video timeout.")
            response = getattr(operation, "response", None)
            videos = getattr(response, "generated_videos", None) or []
            if not videos:
                raise AutoEditorError("BLOCKED_EXTERNAL: AI provider không trả về video.")
            remote_video = videos[0].video
            client.files.download(file=remote_video)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            remote_video.save(str(output_path))
        except AutoEditorError:
            raise
        except Exception as exc:
            raise AutoEditorError(f"BLOCKED_EXTERNAL: AI image-to-video failed: {exc}") from exc


def create_ai_motion_provider(name: str | None, model: str) -> GeminiImageToVideoProvider | UnconfiguredAIMotionProvider:
    if name == "gemini_image_to_video":
        return GeminiImageToVideoProvider(model)
    return UnconfiguredAIMotionProvider()
