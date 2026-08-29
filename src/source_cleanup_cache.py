from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .config import AppConfig
from .media_qc import probe_video
from .models import AutoEditorError
from .source_cleanup import run_frequency_cleanup_pipeline
from .visual_quality import source_cleanup_geometry


CACHE_SCHEMA_VERSION = 1
CLEANUP_IMPLEMENTATION_VERSION = "frequency-reconstruct-v1"


@dataclass(frozen=True)
class CleanupCacheResult:
    path: Path
    key: str
    hit: bool


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cleanup_cache_identity(source: Path, config: AppConfig) -> tuple[str, dict]:
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "implementation_version": CLEANUP_IMPLEMENTATION_VERSION,
        "source_sha256": _sha256(source),
        "cleanup_strategy": config.source_cleanup.strategy,
        "cleanup_config": asdict(config.source_cleanup),
        "video": {
            "width": config.video.width,
            "height": config.video.height,
            "fps": config.video.fps,
        },
    }
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest(), payload


def _read_valid_entry(
    video_path: Path, manifest_path: Path, key: str, identity: dict,
    config: AppConfig,
) -> bool:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("cache_key") != key or manifest.get("identity") != identity:
            return False
        artifact = manifest["artifact"]
        if artifact.get("filename") != video_path.name:
            return False
        if artifact.get("sha256") != _sha256(video_path):
            return False
        info = probe_video(video_path, config.ffprobe)
        return (
            info["width"] == config.video.width
            and info["height"] == config.video.height
            and abs(info["fps"] - config.video.fps) < 0.001
            and info["duration"] > 0
        )
    except (AutoEditorError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def get_or_create_cleanup_cache(
    source: Path,
    cache_dir: Path,
    source_duration: float,
    config: AppConfig,
    *,
    progress: Callable[[str], None] | None = None,
) -> CleanupCacheResult:
    key, identity = cleanup_cache_identity(source, config)
    video_path = cache_dir / f"{key}.mp4"
    manifest_path = cache_dir / f"{key}.json"
    if _read_valid_entry(video_path, manifest_path, key, identity, config):
        if progress:
            progress("HIT")
        return CleanupCacheResult(video_path, key, True)

    if progress:
        progress("MISS")
        progress("PROCESSING")
    cache_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    temporary_video = cache_dir / f".{key}.{token}.tmp.mp4"
    temporary_manifest = cache_dir / f".{key}.{token}.tmp.json"
    diagnostics = cache_dir / f".{key}.{token}.cleanup.json"
    encode_command = [
        config.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pixel_format", "bgr24",
        "-video_size", f"{config.video.width}x{config.video.height}",
        "-framerate", str(config.video.fps), "-i", "pipe:0",
        "-map", "0:v:0", "-an", "-c:v", "libx264rgb", "-crf", "0",
        "-preset", "medium", "-pix_fmt", "bgr24", "-r", str(config.video.fps),
        "-video_track_timescale", "90000", str(temporary_video),
    ]
    try:
        run_frequency_cleanup_pipeline(
            config.ffmpeg, source, encode_command,
            width=config.video.width, height=config.video.height,
            fps=config.video.fps, decode_duration=source_duration,
            geometry=source_cleanup_geometry(
                config.video.width, config.video.height, config.source_cleanup
            ),
            diagnostics_path=diagnostics,
        )
        info = probe_video(temporary_video, config.ffprobe)
        if (
            info["width"] != config.video.width
            or info["height"] != config.video.height
            or abs(info["fps"] - config.video.fps) >= 0.001
            or info["duration"] <= 0
        ):
            raise AutoEditorError("Cache source cleanup không đúng media contract.")

        # Another producer may have completed the same deterministic entry.
        if _read_valid_entry(video_path, manifest_path, key, identity, config):
            return CleanupCacheResult(video_path, key, True)
        manifest = {
            "cache_key": key,
            "identity": identity,
            "artifact": {
                "filename": video_path.name,
                "sha256": _sha256(temporary_video),
                "duration": info["duration"],
                "width": info["width"],
                "height": info["height"],
                "fps": info["fps"],
            },
        }
        temporary_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Publish the media first. Readers require the manifest too, so an
        # interrupted publish can never be treated as a cache hit.
        os.replace(temporary_video, video_path)
        os.replace(temporary_manifest, manifest_path)
        return CleanupCacheResult(video_path, key, False)
    finally:
        for temporary in (temporary_video, temporary_manifest, diagnostics):
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
