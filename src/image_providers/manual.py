from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import AutoEditorError


class ManualImageProvider:
    name = "manual"

    def generate(
        self, prompt: str, output_path: Path, aspect_ratio: str,
        image_size: str, metadata: dict[str, Any],
    ) -> None:
        raise AutoEditorError(
            "Manual image provider không tạo ảnh. Hãy copy ảnh vào input/images và đặt scene.image."
        )
