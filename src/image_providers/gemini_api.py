from __future__ import annotations

import os
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from ..image_prompt_builder import build_retry_prompt
from ..models import AutoEditorError


class GeminiApiImageProvider:
    name = "gemini_api"

    def __init__(
        self, model: str, api_key: str | None = None, max_attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = os.environ.get("GEMINI_IMAGE_MODEL") or model
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.max_attempts = max(1, max_attempts)
        self.sleeper = sleeper
        if not self.api_key:
            raise AutoEditorError(
                "BLOCKED_EXTERNAL: visual.image_provider=gemini_api cần GEMINI_API_KEY."
            )

    @staticmethod
    def _is_non_retryable(exc: Exception) -> bool:
        message = str(exc).casefold()
        return any(token in message for token in (
            "api key", "permission", "unauthorized", "billing", "quota", "resource_exhausted",
        ))

    def _generate_once(self, prompt: str, output_path: Path, aspect_ratio: str, image_size: str) -> None:
        try:
            from google import genai
            from google.genai import types
            from PIL import Image
        except ImportError as exc:
            raise AutoEditorError("Thiếu google-genai/Pillow. Hãy chạy SETUP.bat.") from exc
        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=aspect_ratio, image_size=image_size),
            ),
        )
        parts = getattr(getattr(response, "candidates", [None])[0], "content", None)
        parts = getattr(parts, "parts", [])
        image_data = next(
            (getattr(part.inline_data, "data", None) for part in parts if getattr(part, "inline_data", None)),
            None,
        )
        if not image_data:
            raise AutoEditorError("Gemini không trả về image data.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(BytesIO(image_data)) as image:
            image.save(output_path, format="PNG")

    def generate(
        self, prompt: str, output_path: Path, aspect_ratio: str,
        image_size: str, metadata: dict[str, Any],
    ) -> None:
        current_prompt = prompt
        for attempt in range(1, self.max_attempts + 1):
            try:
                self._generate_once(current_prompt, output_path, aspect_ratio, image_size)
                return
            except AutoEditorError:
                raise
            except Exception as exc:
                if self._is_non_retryable(exc) or attempt == self.max_attempts:
                    raise AutoEditorError(
                        f"BLOCKED_EXTERNAL: Gemini image generation failed after {attempt} attempt(s): {exc}"
                    ) from exc
                current_prompt = build_retry_prompt(prompt)
                self.sleeper(min(2 ** (attempt - 1), 4))
