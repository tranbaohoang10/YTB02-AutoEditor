from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .config import AppConfig, SourceCleanupConfig
from .models import AutoEditorError


@dataclass(frozen=True)
class SceneVisualProfile:
    scene_id: int
    asset_kind: str
    spatial_density: float
    motion_energy: float
    flow_logo_score: float
    density_class: str
    motion_class: str
    cleanup_required: bool
    coverage_shortfall: float = 0.0


def source_cleanup_geometry(
    width: int, height: int, config: SourceCleanupConfig,
) -> tuple[int, int, int, int]:
    """Return an even, frame-contained cleanup rectangle."""
    if width <= 0 or height <= 0:
        raise AutoEditorError("Kích thước source-cleanup phải > 0.")
    x = round(width * config.x_ratio)
    y = round(height * config.y_ratio)
    patch_width = max(16, round(width * config.width_ratio))
    patch_height = max(16, round(height * config.height_ratio))
    x -= x % 2
    y -= y % 2
    patch_width -= patch_width % 2
    patch_height -= patch_height % 2
    patch_width = min(patch_width, width - x)
    patch_height = min(patch_height, height - y)
    if patch_width < 16 or patch_height < 16:
        raise AutoEditorError("Vùng source-cleanup quá nhỏ hoặc nằm ngoài frame.")
    return x, y, patch_width, patch_height


def source_edge_crop_geometry(
    width: int, height: int, config: SourceCleanupConfig,
) -> tuple[int, int]:
    crop_width = max(16, round(width * config.crop_width_ratio))
    crop_height = max(16, round(height * config.crop_height_ratio))
    crop_width -= crop_width % 2
    crop_height -= crop_height % 2
    if crop_width > width or crop_height > height:
        raise AutoEditorError("Safe edge crop phải nằm trong source frame.")
    return crop_width, crop_height


def _draw_flow_gemini_mask(
    width: int, height: int, feather_px: int,
) -> Image.Image:
    """Create a precise two-sparkle alpha mask used by the current Flow clips.

    Coordinates are normalized inside the configured cleanup rectangle so the
    patch remains deterministic if output resolution changes.
    """
    image = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(image)

    def point(x: float, y: float) -> tuple[int, int]:
        return round(x * width), round(y * height)

    main = tuple(point(x, y) for x, y in (
        (0.30, 0.00), (0.365, 0.24), (0.525, 0.375), (0.365, 0.49),
        (0.30, 0.725), (0.235, 0.49), (0.075, 0.375), (0.235, 0.24),
    ))
    secondary = tuple(point(x, y) for x, y in (
        (0.625, 0.38), (0.70, 0.54), (0.95, 0.63), (0.70, 0.72),
        (0.625, 0.95), (0.55, 0.72), (0.40, 0.63), (0.55, 0.54),
    ))
    draw.polygon(main, fill=255)
    draw.polygon(secondary, fill=255)
    if feather_px:
        image = image.filter(ImageFilter.GaussianBlur(feather_px))
    return image


def ensure_flow_gemini_mask(
    directory: Path, width: int, height: int, config: SourceCleanupConfig,
) -> Path:
    _, _, patch_width, patch_height = source_cleanup_geometry(width, height, config)
    destination = directory / f"flow_gemini_mask_v2_{patch_width}x{patch_height}.png"
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    directory.mkdir(parents=True, exist_ok=True)
    mask = _draw_flow_gemini_mask(patch_width, patch_height, config.feather_px)
    mask.save(destination)
    return destination


def _decode_gray_samples(
    source: Path, duration: float, config: AppConfig,
) -> np.ndarray:
    width = config.visual_quality.analysis_width
    height = max(2, round(width * config.video.height / config.video.width))
    height += height % 2
    fps = max(0.05, config.visual_quality.sample_frames / max(duration, 0.05))
    command = [
        config.ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(source),
        "-vf", f"fps={fps:.8f},scale={width}:{height}:flags=area,format=gray",
        "-frames:v", str(config.visual_quality.sample_frames),
        "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ]
    try:
        result = subprocess.run(command, capture_output=True)
    except OSError as exc:
        raise AutoEditorError(f"Không chạy được FFmpeg visual profile: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise AutoEditorError(f"FFmpeg không đọc được visual profile: {detail[-2000:]}")
    frame_size = width * height
    frame_count = len(result.stdout) // frame_size
    if frame_count < 1:
        raise AutoEditorError(f"Không decode được frame visual profile: {source.name}")
    payload = result.stdout[:frame_count * frame_size]
    return np.frombuffer(payload, dtype=np.uint8).reshape(frame_count, height, width)


def _logo_score(frames: np.ndarray, cleanup: SourceCleanupConfig) -> float:
    height, width = frames.shape[1:]
    x, y, patch_width, patch_height = source_cleanup_geometry(width, height, cleanup)
    mask_image = _draw_flow_gemini_mask(patch_width, patch_height, 1)
    mask = np.asarray(mask_image, dtype=np.float32) / 255.0
    blurred_mask = np.asarray(
        mask_image.filter(ImageFilter.GaussianBlur(max(2, patch_width // 10))),
        dtype=np.float32,
    ) / 255.0
    template = mask - blurred_mask
    template_norm = float(np.sqrt(np.square(template).sum()))
    if template_norm <= 1e-6:
        return 0.0
    scores: list[float] = []
    for frame in frames:
        patch = frame[y:y + patch_height, x:x + patch_width].astype(np.float32)
        background = np.asarray(
            Image.fromarray(patch.astype(np.uint8)).filter(
                ImageFilter.GaussianBlur(max(2, patch_width // 10))
            ),
            dtype=np.float32,
        )
        residual = patch - background
        residual_norm = float(np.sqrt(np.square(residual).sum()))
        if residual_norm <= 1e-6:
            scores.append(0.0)
            continue
        correlation = float((residual * template).sum()) / (
            residual_norm * template_norm
        )
        amplitude = float(residual.std()) / 255.0
        scores.append(max(0.0, correlation) * amplitude)
    return max(0.0, max(scores, default=0.0))


def analyze_video_profile(
    scene_id: int, source: Path, duration: float, config: AppConfig,
) -> SceneVisualProfile:
    frames = _decode_gray_samples(source, duration, config)
    normalized = frames.astype(np.float32) / 255.0
    horizontal = np.abs(np.diff(normalized, axis=2)).mean()
    vertical = np.abs(np.diff(normalized, axis=1)).mean()
    density = float((horizontal + vertical) / 2.0)
    motion = (
        float(np.abs(np.diff(normalized, axis=0)).mean())
        if len(normalized) > 1 else 0.0
    )
    quality = config.visual_quality
    return SceneVisualProfile(
        scene_id=scene_id,
        asset_kind="video",
        spatial_density=round(density, 6),
        motion_energy=round(motion, 6),
        flow_logo_score=round(_logo_score(frames, config.source_cleanup), 6),
        density_class="high" if density >= quality.high_density_threshold else "normal",
        motion_class="low" if motion <= quality.low_motion_threshold else "active",
        cleanup_required=config.source_cleanup.enabled,
    )


def neutral_visual_profile(scene_id: int, asset_kind: str) -> SceneVisualProfile:
    return SceneVisualProfile(
        scene_id=scene_id,
        asset_kind=asset_kind,
        spatial_density=0.0,
        motion_energy=0.0,
        flow_logo_score=0.0,
        density_class="normal",
        motion_class="low" if asset_kind == "image" else "active",
        cleanup_required=False,
    )


def write_visual_profile_diagnostics(
    profiles: Sequence[SceneVisualProfile], path: Path,
) -> dict[str, object]:
    records = [asdict(profile) for profile in profiles]
    payload: dict[str, object] = {
        "scene_count": len(records),
        "cleanup_required_count": sum(profile.cleanup_required for profile in profiles),
        "low_motion_count": sum(profile.motion_class == "low" for profile in profiles),
        "high_density_count": sum(profile.density_class == "high" for profile in profiles),
        "maximum_flow_logo_score": round(
            max((profile.flow_logo_score for profile in profiles), default=0.0), 6
        ),
        "profiles": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
