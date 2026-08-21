from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from .models import AutoEditorError


def validate_image(path: Path, minimum_width: int = 640, minimum_height: int = 360) -> tuple[int, int]:
    if not path.is_file() or path.stat().st_size == 0:
        raise AutoEditorError(f"Ảnh rỗng hoặc không tồn tại: {path}")
    try:
        from PIL import Image, UnidentifiedImageError
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
    except ImportError as exc:
        raise AutoEditorError("Thiếu Pillow. Hãy chạy SETUP.bat.") from exc
    except (OSError, UnidentifiedImageError) as exc:
        raise AutoEditorError(f"Ảnh corrupt hoặc không decode được {path}: {exc}") from exc
    if width < minimum_width or height < minimum_height:
        raise AutoEditorError(
            f"Ảnh {path.name} quá nhỏ: {width}x{height}; cần ít nhất {minimum_width}x{minimum_height}."
        )
    if not 0.25 <= width / height <= 4.0:
        raise AutoEditorError(f"Ảnh {path.name} có aspect ratio bất hợp lý: {width}x{height}.")
    return width, height


def probe_video(path: Path, ffprobe: str) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise AutoEditorError(f"Video rỗng hoặc không tồn tại: {path}")
    command = [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate,pix_fmt,color_range:format=duration",
        "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        raise AutoEditorError(f"Không chạy được ffprobe: {exc}") from exc
    if result.returncode != 0:
        raise AutoEditorError(f"ffprobe không đọc được video {path}: {result.stderr.strip()}")
    try:
        data = json.loads(result.stdout)
        stream = data["streams"][0]
        duration = float(data["format"]["duration"])
        width, height = int(stream["width"]), int(stream["height"])
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AutoEditorError(f"Video {path} không có video stream hợp lệ.") from exc
    try:
        fps = float(Fraction(str(stream["r_frame_rate"])))
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        raise AutoEditorError(f"Video {path} có FPS không hợp lệ.") from exc
    if duration <= 0 or width <= 0 or height <= 0 or fps <= 0:
        raise AutoEditorError(f"Video {path} có duration/dimensions/fps không hợp lệ.")
    return {"duration": duration, "width": width, "height": height, "fps": fps, **stream}
