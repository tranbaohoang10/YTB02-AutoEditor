from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

from .models import AutoEditorError


def require_executable(command: str, label: str) -> None:
    executable = Path(command)
    if not executable.is_file() and shutil.which(command) is None:
        raise AutoEditorError(f"Không tìm thấy {label}: {command}")
    try:
        result = subprocess.run(
            [command, "-version"], capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        raise AutoEditorError(f"Không chạy được {label}: {exc}") from exc
    if result.returncode != 0:
        raise AutoEditorError(f"{label} không hoạt động: {(result.stderr or result.stdout).strip()}")


def run_media_command(command: Sequence[str], purpose: str) -> None:
    try:
        result = subprocess.run(
            list(command), capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        raise AutoEditorError(f"Không chạy được FFmpeg khi {purpose}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise AutoEditorError(f"FFmpeg thất bại khi {purpose}:\n{detail[-3000:]}")


def probe_duration(path: Path, ffprobe: str) -> float:
    if not path.is_file() or path.stat().st_size == 0:
        raise AutoEditorError(f"Media file rỗng hoặc không tồn tại: {path}")
    command = [
        ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        raise AutoEditorError(f"Không chạy được ffprobe: {exc}") from exc
    if result.returncode != 0:
        raise AutoEditorError(f"ffprobe không đọc được {path}: {result.stderr.strip()}")
    try:
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AutoEditorError(f"ffprobe không trả về duration hợp lệ cho {path}") from exc
    if duration <= 0:
        raise AutoEditorError(f"Duration không hợp lệ ({duration}) cho {path}")
    return duration


def write_concat_file(paths: Sequence[Path], destination: Path) -> None:
    if not paths:
        raise AutoEditorError("Không có file để concat.")
    lines = []
    for path in paths:
        escaped = path.resolve().as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ffmpeg_filter_path(path: Path) -> str:
    value = path.resolve().as_posix().replace("\\", "/")
    value = value.replace(":", r"\:").replace("'", r"\'")
    return value
