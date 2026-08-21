from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ImageProvider(Protocol):
    name: str

    def generate(
        self, prompt: str, output_path: Path, aspect_ratio: str,
        image_size: str, metadata: dict[str, Any],
    ) -> None: ...
