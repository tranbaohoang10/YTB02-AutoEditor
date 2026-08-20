from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import AutoEditorError


@dataclass(frozen=True)
class VideoConfig:
    width: int
    height: int
    fps: int
    codec: str
    crf: int
    preset: str


@dataclass(frozen=True)
class AudioConfig:
    sample_rate: int
    aac_bitrate: str
    gap_ms: int


@dataclass(frozen=True)
class SubtitleConfig:
    font: str
    font_size: int
    margin_bottom: int
    outline: int
    max_chars_per_line: int
    max_lines: int
    max_words_per_window: int = 6


@dataclass(frozen=True)
class AlignmentConfig:
    engine: str
    device: str
    allow_approximate_fallback: bool
    model_en: str | None
    model_vi: str | None
    cache_dir: Path
    duration_tolerance: float


@dataclass(frozen=True)
class AppConfig:
    kokoro_python: Path
    ffmpeg: str
    ffprobe: str
    video: VideoConfig
    audio: AudioConfig
    subtitles: SubtitleConfig
    alignment: AlignmentConfig


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    if not isinstance(value, dict):
        raise AutoEditorError(f"config.json: thiếu section '{name}'.")
    return value


def load_config(path: Path) -> AppConfig:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AutoEditorError(f"Không tìm thấy config: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AutoEditorError(f"Không đọc được config.json: {exc}") from exc
    try:
        video = _section(data, "video")
        audio = _section(data, "audio")
        subtitles = _section(data, "subtitles")
        alignment = _section(data, "alignment")
        fallback_value = alignment["allow_approximate_fallback"]
        if not isinstance(fallback_value, bool):
            raise TypeError("alignment.allow_approximate_fallback phải là boolean")
        kokoro_python = Path(str(data["kokoro_python"]))
        if not kokoro_python.is_absolute():
            kokoro_python = (path.parent / kokoro_python).resolve()
        result = AppConfig(
            kokoro_python=kokoro_python,
            ffmpeg=str(data["ffmpeg"]),
            ffprobe=str(data["ffprobe"]),
            video=VideoConfig(
                width=int(video["width"]), height=int(video["height"]),
                fps=int(video["fps"]), codec=str(video["codec"]),
                crf=int(video["crf"]), preset=str(video["preset"]),
            ),
            audio=AudioConfig(
                sample_rate=int(audio["sample_rate"]),
                aac_bitrate=str(audio["aac_bitrate"]),
                gap_ms=int(audio["gap_ms"]),
            ),
            subtitles=SubtitleConfig(
                font=str(subtitles["font"]), font_size=int(subtitles["font_size"]),
                margin_bottom=int(subtitles["margin_bottom"]),
                outline=int(subtitles["outline"]),
                max_chars_per_line=int(subtitles["max_chars_per_line"]),
                max_lines=int(subtitles["max_lines"]),
                max_words_per_window=int(subtitles.get("max_words_per_window", 6)),
            ),
            alignment=AlignmentConfig(
                engine=str(alignment["engine"]),
                device=str(alignment["device"]),
                allow_approximate_fallback=fallback_value,
                model_en=(str(alignment["model_en"]) if alignment.get("model_en") else None),
                model_vi=(str(alignment["model_vi"]) if alignment.get("model_vi") else None),
                cache_dir=(path.parent / str(alignment["cache_dir"])).resolve()
                if not Path(str(alignment["cache_dir"])).is_absolute()
                else Path(str(alignment["cache_dir"])),
                duration_tolerance=float(alignment.get("duration_tolerance", 0.25)),
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AutoEditorError(f"config.json có giá trị thiếu hoặc không hợp lệ: {exc}") from exc
    if result.video.width <= 0 or result.video.height <= 0 or result.video.fps <= 0:
        raise AutoEditorError("Kích thước và FPS trong config phải lớn hơn 0.")
    if result.audio.sample_rate <= 0 or result.audio.gap_ms < 0:
        raise AutoEditorError("sample_rate phải > 0 và gap_ms phải >= 0.")
    if result.alignment.engine != "whisperx":
        raise AutoEditorError("alignment.engine hiện chỉ hỗ trợ 'whisperx'.")
    if result.alignment.device != "cpu":
        raise AutoEditorError("MVP alignment chỉ hỗ trợ device='cpu'.")
    if result.alignment.duration_tolerance < 0:
        raise AutoEditorError("alignment.duration_tolerance không được âm.")
    if result.subtitles.max_lines < 1 or result.subtitles.max_words_per_window < 1:
        raise AutoEditorError("Subtitle max_lines và max_words_per_window phải >= 1.")
    return result
