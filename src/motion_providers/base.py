from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class MotionProvider(Protocol):
    name: str

    def generate(
        self, image_path: Path, output_path: Path, duration: float,
        prompt: str, metadata: dict[str, Any],
    ) -> None: ...
