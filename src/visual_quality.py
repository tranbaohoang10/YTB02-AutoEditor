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
from .source_cleanup import flow_watermark_support_image


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
    subtitle_density: float = 0.0
    subtitle_background_class: str = "normal"
    hierarchy_adjustment: str = "none"
    focal_region: str | None = None
    hierarchy_reason: str = "density_below_threshold"


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


def source_paper_patch_geometry(
    width: int, height: int, config: SourceCleanupConfig,
) -> tuple[int, int, int, int]:
    """Expand the known logo ROI only enough to hide the torn-paper edge."""
    x, y, patch_width, patch_height = source_cleanup_geometry(width, height, config)
    margin = config.paper_margin_px
    left = max(0, x - margin)
    top = max(0, y - margin)
    right = min(width, x + patch_width + margin)
    bottom = min(height, y + patch_height + margin)
    expanded_width = right - left
    expanded_height = bottom - top
    expanded_width -= expanded_width % 2
    expanded_height -= expanded_height % 2
    if expanded_width < patch_width or expanded_height < patch_height:
        raise AutoEditorError("Paper corner patch không phủ đủ logo ROI.")
    return left, top, expanded_width, expanded_height


def _paper_corner_patch(width: int, height: int, feather_px: int) -> Image.Image:
    """Build a deterministic matte paper patch with soft, irregular torn edges."""
    rng = np.random.default_rng(0x10C1 + width * 31 + height)
    grain = rng.normal(0.0, 5.0, size=(height, width))
    coarse_height = max(2, (height + 15) // 16)
    coarse_width = max(2, (width + 15) // 16)
    coarse = rng.normal(0.0, 1.8, size=(coarse_height, coarse_width))
    coarse_image = Image.fromarray(
        np.clip(coarse * 16 + 128, 0, 255).astype(np.uint8)
    ).resize((width, height), Image.Resampling.BILINEAR)
    grain += (np.asarray(coarse_image, dtype=np.float32) - 128.0) / 16.0
    base = np.empty((height, width, 4), dtype=np.uint8)
    palette = (211, 199, 173)
    for channel, value in enumerate(palette):
        base[:, :, channel] = np.clip(value + grain, 0, 255)

    alpha = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(alpha)

    inset = 14
    step = 11
    edge = 5
    top_edge = [
        (x, inset + ((x * 7 + 3) % edge))
        for x in range(inset, width - inset + 1, step)
    ]
    right_edge = [
        (width - inset - ((y * 5 + 1) % edge), y)
        for y in range(inset, height - inset + 1, step)
    ]
    bottom_edge = [
        (x, height - inset - ((x * 3 + 2) % edge))
        for x in range(width - inset, inset - 1, -step)
    ]
    left_edge = [
        (inset + ((y * 7 + 4) % edge), y)
        for y in range(height - inset, inset - 1, -step)
    ]
    draw.polygon([*top_edge, *right_edge, *bottom_edge, *left_edge], fill=255)
    if feather_px:
        alpha = alpha.filter(ImageFilter.GaussianBlur(min(3, feather_px)))
    base[:, :, 3] = np.asarray(alpha, dtype=np.uint8)
    return Image.fromarray(base)


def ensure_paper_corner_patch(
    directory: Path, width: int, height: int, config: SourceCleanupConfig,
) -> Path:
    _, _, patch_width, patch_height = source_paper_patch_geometry(width, height, config)
    destination = directory / f"paper_corner_patch_v6_{patch_width}x{patch_height}.png"
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    directory.mkdir(parents=True, exist_ok=True)
    _paper_corner_patch(patch_width, patch_height, config.feather_px).save(destination)
    return destination


def _draw_flow_gemini_mask(
    width: int, height: int, feather_px: int,
) -> Image.Image:
    """Create the measured max Flow-mark envelope plus local safety margin."""
    return flow_watermark_support_image(width, height, feather_px)


def ensure_flow_gemini_mask(
    directory: Path, width: int, height: int, config: SourceCleanupConfig,
) -> Path:
    _, _, patch_width, patch_height = source_cleanup_geometry(width, height, config)
    destination = directory / (
        f"flow_gemini_mask_v6_{patch_width}x{patch_height}_f{config.feather_px}.png"
    )
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
    subtitle_top = max(0, round(normalized.shape[1] * 0.72))
    subtitle_bottom = max(subtitle_top + 2, round(normalized.shape[1] * 0.94))
    subtitle_right = max(2, round(normalized.shape[2] * 0.82))
    subtitle_band = normalized[:, subtitle_top:subtitle_bottom, :subtitle_right]
    subtitle_horizontal = np.abs(np.diff(subtitle_band, axis=2)).mean()
    subtitle_vertical = np.abs(np.diff(subtitle_band, axis=1)).mean()
    subtitle_density = float((subtitle_horizontal + subtitle_vertical) / 2.0)
    quality = config.visual_quality
    density_high = density >= quality.high_density_threshold
    subtitle_dense = subtitle_density >= quality.subtitle_density_threshold
    return SceneVisualProfile(
        scene_id=scene_id,
        asset_kind="video",
        spatial_density=round(density, 6),
        motion_energy=round(motion, 6),
        flow_logo_score=round(_logo_score(frames, config.source_cleanup), 6),
        density_class="high" if density_high else "normal",
        motion_class="low" if motion <= quality.low_motion_threshold else "active",
        cleanup_required=config.source_cleanup.enabled,
        subtitle_density=round(subtitle_density, 6),
        subtitle_background_class="high" if subtitle_dense else "normal",
        hierarchy_adjustment=(
            "mild_eq_vignette" if density_high else "none"
        ),
        focal_region=None,
        hierarchy_reason=(
            "spatial_density_above_threshold" if density_high
            else "density_below_threshold"
        ),
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
    *, config: AppConfig | None = None,
) -> dict[str, object]:
    records = [asdict(profile) for profile in profiles]
    payload: dict[str, object] = {
        "scene_count": len(records),
        "cleanup_required_count": sum(profile.cleanup_required for profile in profiles),
        "low_motion_count": sum(profile.motion_class == "low" for profile in profiles),
        "high_density_count": sum(profile.density_class == "high" for profile in profiles),
        "subtitle_dense_count": sum(
            profile.subtitle_background_class == "high" for profile in profiles
        ),
        "maximum_flow_logo_score": round(
            max((profile.flow_logo_score for profile in profiles), default=0.0), 6
        ),
        "profiles": records,
    }
    if config is not None:
        cleanup = config.source_cleanup
        if cleanup.strategy == "paper_corner_patch":
            patch_x, patch_y, patch_width, patch_height = source_paper_patch_geometry(
                config.video.width, config.video.height, cleanup
            )
            alpha = np.asarray(
                _paper_corner_patch(patch_width, patch_height, cleanup.feather_px)
            )[:, :, 3]
            affected_ratio = float(np.count_nonzero(alpha)) / (
                config.video.width * config.video.height
            )
        elif cleanup.strategy == "safe_edge_crop":
            crop_width, crop_height = source_edge_crop_geometry(
                config.video.width, config.video.height, cleanup
            )
            patch_x, patch_y, patch_width, patch_height = (
                0, 0, crop_width, crop_height
            )
            affected_ratio = 1.0 - (
                crop_width * crop_height / (config.video.width * config.video.height)
            )
        elif cleanup.strategy in {
            "frequency_selective_reconstruct", "masked_median_blend",
            "median_texture_patch",
        }:
            patch_x, patch_y, patch_width, patch_height = source_cleanup_geometry(
                config.video.width, config.video.height, cleanup
            )
            mask = np.asarray(
                _draw_flow_gemini_mask(
                    patch_width, patch_height, cleanup.feather_px
                ),
                dtype=np.uint8,
            )
            affected_ratio = float(np.count_nonzero(mask)) / (
                config.video.width * config.video.height
            )
        else:
            patch_x, patch_y, patch_width, patch_height = source_cleanup_geometry(
                config.video.width, config.video.height, cleanup
            )
            affected_ratio = patch_width * patch_height / (
                config.video.width * config.video.height
            )
        payload["cleanup"] = {
            "strategy": cleanup.strategy,
            "global_crop_default": cleanup.strategy == "safe_edge_crop",
            "affected_frame_ratio": round(affected_ratio, 6),
            "geometry": [patch_x, patch_y, patch_width, patch_height],
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
