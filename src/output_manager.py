from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import AppConfig
from .models import AutoEditorError, Script


_INVALID_WINDOWS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_WINDOWS = {
    "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass(frozen=True)
class OutputReservation:
    final_path: Path
    temporary_path: Path
    metadata_path: Path
    number: int
    topic_slug: str
    language_tag: str


def safe_topic_slug(topic: str, *, max_length: int = 80) -> str:
    raw = topic.strip()
    if not raw or Path(raw).is_absolute() or raw.startswith(("\\\\", "//")):
        raise AutoEditorError("Topic output không được trống/absolute/UNC.")
    if any(part == ".." for part in re.split(r"[\\/]", raw)):
        raise AutoEditorError("Topic output không được chứa path traversal '..'.")
    slug = _INVALID_WINDOWS.sub(" ", raw)
    slug = re.sub(r"\s+", "_", slug).strip(" ._")
    slug = re.sub(r"_+", "_", slug)[:max_length].rstrip(" ._")
    device_stem = slug.split(".", 1)[0].upper()
    if not slug or device_stem in _RESERVED_WINDOWS:
        raise AutoEditorError("Topic output không tạo được Windows-safe slug.")
    return slug


def output_scope(output_root: Path, script: Script) -> tuple[Path, str, str]:
    slug = safe_topic_slug(script.topic)
    language_tag = script.language.upper()
    if language_tag not in {"EN", "VI"}:
        raise AutoEditorError("Output language hiện chỉ hỗ trợ EN hoặc VI.")
    directory = output_root / slug / f"Part_{script.part:02d}" / language_tag
    return directory, slug, language_tag


def reserve_output(output_root: Path, script: Script) -> OutputReservation:
    directory, slug, language_tag = output_scope(output_root, script)
    directory.mkdir(parents=True, exist_ok=True)
    prefix = f"{slug}_Part_{script.part:02d}_{language_tag}"
    pattern = re.compile(re.escape(prefix) + r"_([0-9]+)\.mp4\Z")
    for _ in range(100):
        numbers = [
            int(match.group(1))
            for path in directory.iterdir() if path.is_file()
            if (match := pattern.fullmatch(path.name)) is not None
        ]
        number = max(numbers, default=0) + 1
        final_path = directory / f"{prefix}_{number}.mp4"
        try:
            descriptor = os.open(final_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        os.close(descriptor)
        return OutputReservation(
            final_path=final_path,
            temporary_path=directory / f".{prefix}_{number}.building.mp4",
            metadata_path=directory / f"{prefix}_{number}.json",
            number=number,
            topic_slug=slug,
            language_tag=language_tag,
        )
    raise AutoEditorError("Không thể reserve output do quá nhiều build đồng thời.")


def validate_final_media(path: Path, config: AppConfig) -> dict[str, object]:
    command = [
        config.ffprobe, "-v", "error", "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,pix_fmt,"
        "r_frame_rate,color_space,sample_rate,channels",
        "-of", "json", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise AutoEditorError(f"ffprobe không đọc được final media: {result.stderr.strip()}")
    try:
        payload = json.loads(result.stdout)
        duration = float(payload["format"]["duration"])
        streams = payload["streams"]
        video = next(item for item in streams if item.get("codec_type") == "video")
        audio = next(item for item in streams if item.get("codec_type") == "audio")
    except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AutoEditorError("Final media thiếu video/audio hoặc duration hợp lệ.") from exc
    expected = config.video
    checks = {
        "video_codec": video.get("codec_name") == "h264",
        "resolution": (video.get("width"), video.get("height")) == (expected.width, expected.height),
        "pixel_format": video.get("pix_fmt") == "yuv420p",
        "fps": video.get("r_frame_rate") == f"{expected.fps}/1",
        "color_space": video.get("color_space") == "bt709",
        "audio_codec": audio.get("codec_name") == "aac",
        "audio_rate": str(audio.get("sample_rate")) == str(config.audio.mix_sample_rate),
        "audio_channels": audio.get("channels") == 2,
        "duration_positive": duration > 0,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise AutoEditorError(f"Final media validation thất bại: {', '.join(failed)}")
    return {"duration": duration, "checks": checks}


def publish_output(
    reservation: OutputReservation, script: Script, config: AppConfig,
) -> dict[str, object]:
    if not reservation.final_path.is_file() or reservation.final_path.stat().st_size != 0:
        raise AutoEditorError("Output reservation không còn thuộc build hiện tại.")
    validation = validate_final_media(reservation.temporary_path, config)
    os.replace(reservation.temporary_path, reservation.final_path)
    metadata = {
        "topic": script.topic,
        "topic_slug": reservation.topic_slug,
        "part": script.part,
        "title": script.title,
        "language": script.language,
        "language_tag": reservation.language_tag,
        "voice": script.voice,
        "speed": script.speed,
        "number": reservation.number,
        "video": reservation.final_path.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **validation,
    }
    temporary_metadata = reservation.metadata_path.with_suffix(".json.building")
    temporary_metadata.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary_metadata, reservation.metadata_path)
    return metadata
