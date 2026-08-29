from __future__ import annotations

import base64
import io
import json
import math
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image, ImageFilter

from .models import AutoEditorError


# Robust per-pixel alpha template measured from the fixed-screen Flow sparkle
# across all 30 Black Wednesday source clips. Keeping the calibrated template
# embedded makes cleanup deterministic and independent of files under work/.
_FLOW_ALPHA_PNG = (
    "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"
)


def _cv2():
    try:
        import cv2
    except ImportError as exc:
        raise AutoEditorError(
            "Thiếu opencv-python-headless cho source-logo cleanup. Hãy chạy SETUP.bat."
        ) from exc
    return cv2


@lru_cache(maxsize=8)
def flow_watermark_alpha(width: int, height: int) -> np.ndarray:
    if width < 16 or height < 16:
        raise AutoEditorError("Flow alpha template yêu cầu ROI tối thiểu 16x16.")
    with Image.open(io.BytesIO(base64.b64decode(_FLOW_ALPHA_PNG))) as source:
        image = source.convert("L")
        if image.size != (width, height):
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        return np.asarray(image, dtype=np.float32) / 255.0


def flow_watermark_support_image(
    width: int, height: int, feather_px: int,
) -> Image.Image:
    """Return the measured max mark envelope plus a deterministic 4 px margin."""
    alpha = flow_watermark_alpha(width, height)
    support = Image.fromarray((alpha > (3.0 / 255.0)).astype(np.uint8) * 255)
    margin = max(1, round(4 * width / 200))
    support = support.filter(ImageFilter.MaxFilter(margin * 2 + 1))
    if feather_px:
        support = support.filter(ImageFilter.GaussianBlur(feather_px))
    return support


def _frequency_reconstruct_flow_watermark(
    frame: np.ndarray, geometry: tuple[int, int, int, int],
) -> tuple[np.ndarray, dict[str, float]]:
    """Remove the Flow sparkle while preserving local paper/halftone texture.

    The low-frequency watermark brightness is reconstructed from the surrounding
    pixels. Real high-frequency texture is retained after inverse alpha
    compositing, while only the alpha edge borrows high-frequency detail from
    three nearby, watermark-free patches. No pixel outside the measured support
    envelope is changed.
    """
    cv2 = _cv2()
    x, y, width, height = geometry
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise AutoEditorError("Source cleanup yêu cầu frame BGR 3 kênh.")
    if x < 0 or y < 0 or x + width > frame.shape[1] or y + height > frame.shape[0]:
        raise AutoEditorError("Source-cleanup ROI nằm ngoài frame.")

    alpha = flow_watermark_alpha(width, height)
    source = frame[y:y + height, x:x + width].astype(np.float32)
    support = np.asarray(
        flow_watermark_support_image(width, height, 0), dtype=np.uint8
    )
    expected = cv2.inpaint(source.astype(np.uint8), support, 5, cv2.INPAINT_TELEA)
    expected_low = cv2.GaussianBlur(expected.astype(np.float32), (0, 0), 2.6)
    observed_low = cv2.GaussianBlur(source, (0, 0), 2.6)
    weight = cv2.GaussianBlur(
        (alpha > 0.05).astype(np.float32), (0, 0), 2.0
    )

    best: tuple[float, float, float] | None = None
    for foreground in (242.0, 248.0, 255.0):
        model = alpha[:, :, None] * (foreground - expected_low)
        weighted_model = weight[:, :, None] * model
        denominator = float(np.sum(weighted_model * model))
        opacity_scale = float(
            np.sum(weighted_model * (observed_low - expected_low))
            / max(1.0, denominator)
        )
        opacity_scale = min(2.05, max(0.75, opacity_scale))
        error = float(np.sum(
            weight[:, :, None]
            * np.abs((observed_low - expected_low) - opacity_scale * model)
        ))
        if best is None or error < best[0]:
            best = (error, opacity_scale, foreground)
    assert best is not None
    _, opacity_scale, foreground = best

    scaled_alpha = np.clip(alpha * opacity_scale, 0.0, 0.66)
    repaired = (
        source - scaled_alpha[:, :, None] * foreground
    ) / np.maximum(0.34, 1.0 - scaled_alpha[:, :, None])
    repaired_low = cv2.GaussianBlur(repaired, (0, 0), 2.6)
    repaired_high = repaired - repaired_low

    texture_samples: list[np.ndarray] = []
    for dx, dy in ((-140, 0), (0, -140), (-100, -100)):
        sample_x = min(max(0, x + dx), frame.shape[1] - width)
        sample_y = min(max(0, y + dy), frame.shape[0] - height)
        patch = frame[
            sample_y:sample_y + height, sample_x:sample_x + width
        ].astype(np.float32)
        texture_samples.append(
            patch - cv2.GaussianBlur(patch, (0, 0), 1.8)
        )
    texture_high = np.median(np.stack(texture_samples), axis=0)

    gradient_x = cv2.Sobel(alpha, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(alpha, cv2.CV_32F, 0, 1, ksize=3)
    edge = np.clip(
        cv2.GaussianBlur(
            cv2.magnitude(gradient_x, gradient_y), (0, 0), 1.0
        ) * 7.0,
        0.0, 1.0,
    )
    high = (
        repaired_high * (1.0 - edge[:, :, None])
        + texture_high * edge[:, :, None]
    )
    reconstructed = expected_low + high
    support_soft = cv2.GaussianBlur(
        support, (0, 0), 2.0
    ).astype(np.float32)[:, :, None] / 255.0
    repaired = repaired * (1.0 - support_soft) + reconstructed * support_soft

    output = frame.copy()
    output[y:y + height, x:x + width] = np.clip(
        repaired, 0, 255
    ).astype(np.uint8)
    return output, {
        "opacity_scale": round(opacity_scale, 6),
        "foreground": foreground,
        "affected_ratio": round(
            float(np.count_nonzero(support)) / (frame.shape[0] * frame.shape[1]), 8
        ),
    }


def _template_deblend(
    frame: np.ndarray,
    geometry: tuple[int, int, int, int],
    *,
    normalized_selection: bool,
) -> tuple[np.ndarray, dict[str, float]]:
    cv2 = _cv2()
    x, y, width, height = geometry
    alpha = flow_watermark_alpha(width, height)
    source = frame[y:y + height, x:x + width].astype(np.float32)
    broad = (alpha > 0.003).astype(np.uint8) * 255
    dilation = max(3, round(17 * width / 200)) | 1
    broad = cv2.dilate(
        broad, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilation, dilation))
    )
    expected = cv2.inpaint(source.astype(np.uint8), broad, 5, cv2.INPAINT_TELEA)
    expected_low = cv2.GaussianBlur(expected.astype(np.float32), (0, 0), 2.2)
    observed_low = cv2.GaussianBlur(source, (0, 0), 2.2)
    delta = observed_low - expected_low
    center = (width * 0.30, height * 0.375)
    best = None
    for spatial_scale in np.linspace(0.65, 1.55, 19):
        variant = cv2.warpAffine(
            alpha, cv2.getRotationMatrix2D(center, 0.0, float(spatial_scale)),
            (width, height), flags=cv2.INTER_LINEAR,
        )
        weight = cv2.GaussianBlur(
            (variant > 0.008).astype(np.float32), (0, 0), 1.5
        )
        baseline = float(np.sum(weight[:, :, None] * np.abs(delta)))
        for foreground in (242.0, 248.0, 255.0):
            model = variant[:, :, None] * (foreground - expected_low)
            denominator = float(np.sum(weight[:, :, None] * model * model))
            opacity = float(
                np.sum(weight[:, :, None] * model * delta) / max(1.0, denominator)
            )
            opacity = min(2.4, max(0.0, opacity))
            error = float(np.sum(
                weight[:, :, None] * np.abs(delta - opacity * model)
            ))
            relative_error = error / max(1.0, baseline)
            selection_error = relative_error if normalized_selection else error
            if best is None or selection_error < best[0]:
                best = (
                    selection_error, float(spatial_scale), opacity, foreground,
                    variant, relative_error,
                )
    assert best is not None
    _, spatial_scale, opacity, foreground, variant, relative_error = best
    gain = 1.0 - relative_error
    stats = {
        "opacity_scale": round(opacity, 6),
        "size_percent": round(spatial_scale * 100),
        "gain_percent": round(gain * 100),
        "affected_ratio": 0.0,
    }
    if opacity < 0.12 or gain < 0.20:
        return frame.copy(), stats

    template = variant - cv2.GaussianBlur(variant, (0, 0), 7.0)
    template_norm = max(1.0, float(np.sqrt(np.sum(template * template))))
    tuned = None
    for tuned_opacity in np.linspace(
        max(0.05, opacity * 0.45), min(3.0, opacity * 1.9), 48
    ):
        candidate_alpha = np.clip(variant * tuned_opacity, 0.0, 0.82)
        candidate = (
            source - candidate_alpha[:, :, None] * foreground
        ) / np.maximum(0.18, 1.0 - candidate_alpha[:, :, None])
        gray = cv2.cvtColor(
            np.clip(candidate, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY
        ).astype(np.float32)
        residual = gray - cv2.GaussianBlur(gray, (0, 0), 7.0)
        response = abs(float(np.sum(residual * template))) / template_norm
        clipping = float(np.mean((candidate < -2.0) | (candidate > 257.0))) * 1500.0
        objective = response + clipping
        if tuned is None or objective < tuned[0]:
            tuned = (objective, float(tuned_opacity), candidate)
    assert tuned is not None
    _, opacity, repaired = tuned
    support = cv2.GaussianBlur(
        (variant > 0.003).astype(np.float32), (0, 0), 0.8
    )[:, :, None]
    output = frame.copy()
    output[y:y + height, x:x + width] = np.clip(
        source * (1.0 - support) + repaired * support, 0, 255
    ).astype(np.uint8)
    stats["opacity_scale"] = round(opacity, 6)
    stats["affected_ratio"] = round(
        float(np.count_nonzero(support)) / (frame.shape[0] * frame.shape[1]), 8
    )
    return output, stats


def _patchmatch_reconstruct(
    frame: np.ndarray,
    geometry: tuple[int, int, int, int],
    detection: dict[str, float],
) -> tuple[np.ndarray, dict[str, float]]:
    cv2 = _cv2()
    x, y, width, height = geometry
    alpha = flow_watermark_alpha(width, height)
    spatial_scale = float(detection["size_percent"]) / 100.0
    variant = cv2.warpAffine(
        alpha,
        cv2.getRotationMatrix2D((width * 0.30, height * 0.375), 0.0, spatial_scale),
        (width, height), flags=cv2.INTER_LINEAR,
    )
    local_mask = (variant > 0.007).astype(np.uint8)
    dilation = max(3, round(7 * width / 200)) | 1
    local_mask = cv2.dilate(
        local_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilation, dilation))
    )
    left = max(0, x - round(2.2 * width))
    top = max(0, y - round(1.5 * height))
    right = min(frame.shape[1], x + width + round(0.1 * width))
    bottom = min(frame.shape[0], y + height + round(0.1 * height))
    crop = frame[top:bottom, left:right].copy()
    mask = np.zeros(crop.shape[:2], np.uint8)
    roi_left, roi_top = x - left, y - top
    mask[roi_top:roi_top + height, roi_left:roi_left + width] = local_mask
    original_mask = mask.copy()
    working = crop.copy()
    radius = max(3, round(6 * width / 200))
    patch_size = radius * 2 + 1
    iterations = 0
    kernel = np.ones((3, 3), np.uint8)
    while np.any(mask) and iterations < 500:
        boundary = (mask > 0) & (cv2.erode(mask, kernel) == 0)
        ys, xs = np.where(boundary)
        valid = (
            (xs >= radius) & (ys >= radius)
            & (xs < crop.shape[1] - radius) & (ys < crop.shape[0] - radius)
        )
        xs, ys = xs[valid], ys[valid]
        if len(xs) == 0:
            break
        counts = cv2.boxFilter(
            (mask == 0).astype(np.float32), -1, (patch_size, patch_size),
            normalize=False, borderType=cv2.BORDER_CONSTANT,
        )[ys, xs]
        order = np.lexsort((xs, ys, -counts))
        center_x, center_y = int(xs[order[0]]), int(ys[order[0]])
        patch_left, patch_top = center_x - radius, center_y - radius
        target_patch = working[
            patch_top:patch_top + patch_size, patch_left:patch_left + patch_size
        ]
        target_unknown = mask[
            patch_top:patch_top + patch_size, patch_left:patch_left + patch_size
        ] > 0
        known = (~target_unknown).astype(np.uint8) * 255
        scores = cv2.matchTemplate(
            working, target_patch, cv2.TM_SQDIFF,
            mask=np.repeat(known[:, :, None], 3, axis=2),
        )
        invalid_sums = cv2.boxFilter(
            original_mask, cv2.CV_32S, (patch_size, patch_size),
            normalize=False, anchor=(0, 0), borderType=cv2.BORDER_CONSTANT,
        )
        scores[invalid_sums[:scores.shape[0], :scores.shape[1]] > 0] = np.inf
        if not np.isfinite(scores).any():
            break
        source_top, source_left = np.unravel_index(np.argmin(scores), scores.shape)
        source_patch = working[
            source_top:source_top + patch_size, source_left:source_left + patch_size
        ]
        destination = working[
            patch_top:patch_top + patch_size, patch_left:patch_left + patch_size
        ]
        destination[target_unknown] = source_patch[target_unknown]
        mask[
            patch_top:patch_top + patch_size, patch_left:patch_left + patch_size
        ][target_unknown] = 0
        iterations += 1
    if np.any(mask):
        working = cv2.inpaint(working, mask * 255, 3, cv2.INPAINT_TELEA)
    repaired = working[
        roi_top:roi_top + height, roi_left:roi_left + width
    ].astype(np.float32)
    source = frame[y:y + height, x:x + width].astype(np.float32)
    soft = cv2.GaussianBlur(
        local_mask.astype(np.float32), (0, 0), 0.65
    )[:, :, None]
    output = frame.copy()
    output[y:y + height, x:x + width] = np.clip(
        source * (1.0 - soft) + repaired * soft, 0, 255
    ).astype(np.uint8)
    stats = dict(detection)
    stats.update({
        "method": "patchmatch",
        "iterations": float(iterations),
        "affected_ratio": round(
            float(np.count_nonzero(local_mask)) / (frame.shape[0] * frame.shape[1]), 8
        ),
    })
    return output, stats


def _dark_copy_reconstruct(
    frame: np.ndarray,
    geometry: tuple[int, int, int, int],
    detection: dict[str, float],
) -> tuple[np.ndarray, dict[str, float]]:
    cv2 = _cv2()
    x, y, width, height = geometry
    alpha = flow_watermark_alpha(width, height)
    spatial_scale = float(detection["size_percent"]) / 100.0
    variant = cv2.warpAffine(
        alpha,
        cv2.getRotationMatrix2D((width * 0.30, height * 0.375), 0.0, spatial_scale),
        (width, height), flags=cv2.INTER_LINEAR,
    )
    local_mask = (variant > 0.007).astype(np.uint8)
    dilation = max(3, round(7 * width / 200)) | 1
    local_mask = cv2.dilate(
        local_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilation, dilation))
    )
    rows, columns = np.where(local_mask > 0)
    left, right = int(columns.min()), int(columns.max()) + 1
    top, bottom = int(rows.min()), int(rows.max()) + 1
    destination = frame[y + top:y + bottom, x + left:x + right]
    mask_patch = local_mask[top:bottom, left:right]
    outer = cv2.dilate(
        mask_patch,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17)),
    )
    ring = (outer > 0) & (mask_patch == 0)
    target_gray = cv2.cvtColor(destination, cv2.COLOR_BGR2GRAY).astype(np.float32)
    best = None
    scale = width / 200.0
    for dx0 in (-32, -24, -16, -8, 0, 8, 16, 24, 32):
        for dy0 in (-220, -180, -150, -125, -105, -85, 85, 105, 125, 150, 180):
            dx, dy = round(dx0 * scale), round(dy0 * scale)
            source_left, source_top = x + left + dx, y + top + dy
            if (
                source_left < 0 or source_top < 0
                or source_left + destination.shape[1] > frame.shape[1]
                or source_top + destination.shape[0] > frame.shape[0]
            ):
                continue
            candidate = frame[
                source_top:source_top + destination.shape[0],
                source_left:source_left + destination.shape[1],
            ]
            candidate_gray = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY).astype(np.float32)
            delta = float(np.median(target_gray[ring]) - np.median(candidate_gray[ring]))
            difference = target_gray[ring] - (candidate_gray[ring] + delta)
            penalty = max(
                0.0, float(np.mean(candidate_gray[mask_patch > 0])) - 55.0
            ) ** 2
            cost = float(np.mean(difference * difference) + 0.8 * penalty)
            if best is None or cost < best[0]:
                best = (cost, candidate.astype(np.float32), delta)
    if best is None:
        return _patchmatch_reconstruct(frame, geometry, detection)
    _, candidate, delta = best
    candidate += delta
    soft = cv2.GaussianBlur(
        mask_patch.astype(np.float32), (0, 0), 0.8
    )[:, :, None]
    output = frame.copy()
    output[y + top:y + bottom, x + left:x + right] = np.clip(
        destination.astype(np.float32) * (1.0 - soft) + candidate * soft, 0, 255
    ).astype(np.uint8)
    stats = dict(detection)
    stats.update({
        "method": "dark_copy",
        "affected_ratio": round(
            float(np.count_nonzero(mask_patch)) / (frame.shape[0] * frame.shape[1]), 8
        ),
    })
    return output, stats


def reconstruct_flow_watermark(
    frame: np.ndarray, geometry: tuple[int, int, int, int],
) -> tuple[np.ndarray, dict[str, float]]:
    """Deterministically remove only detected Flow sparkle pixels in the ROI."""
    x, y, width, height = geometry
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise AutoEditorError("Source cleanup yêu cầu frame BGR 3 kênh.")
    if x < 0 or y < 0 or x + width > frame.shape[1] or y + height > frame.shape[0]:
        raise AutoEditorError("Source-cleanup ROI nằm ngoài frame.")
    if width < 80 or height < 80:
        return _frequency_reconstruct_flow_watermark(frame, geometry)

    _, detection = _template_deblend(
        frame, geometry, normalized_selection=True
    )
    if detection["gain_percent"] < 30:
        stats = dict(detection)
        stats["method"] = "pass_through"
        return frame.copy(), stats

    cv2 = _cv2()
    alpha = flow_watermark_alpha(width, height)
    gray = cv2.cvtColor(
        frame[y:y + height, x:x + width], cv2.COLOR_BGR2GRAY
    )
    core = alpha > 0.01
    ring_kernel = max(3, round(15 * width / 200)) | 1
    ring = (
        cv2.dilate(core.astype(np.uint8), np.ones((ring_kernel, ring_kernel), np.uint8)) > 0
    ) & (~core)
    ring_median = float(np.median(gray[ring]))
    if ring_median < 50:
        return _dark_copy_reconstruct(frame, geometry, detection)
    if detection["size_percent"] < 90 and detection["opacity_scale"] <= 1.2:
        cleaned, stats = _template_deblend(
            frame, geometry, normalized_selection=False
        )
        stats["method"] = "template_deblend"
        return cleaned, stats
    return _patchmatch_reconstruct(frame, geometry, detection)


def _read_exact(stream, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def run_frequency_cleanup_pipeline(
    ffmpeg: str,
    source: Path,
    encode_command: Sequence[str],
    *,
    width: int,
    height: int,
    fps: int,
    decode_duration: float,
    geometry: tuple[int, int, int, int],
    diagnostics_path: Path | None = None,
) -> None:
    """Stream normalized frames through local cleanup into the final encoder."""
    normalize = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={fps},setsar=1"
    )
    decode_command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(source),
        "-vf", normalize, "-an", "-frames:v",
        str(max(1, math.ceil(decode_duration * fps - 1e-9))),
        "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1",
    ]
    try:
        decoder = subprocess.Popen(
            decode_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        encoder = subprocess.Popen(
            list(encode_command), stdin=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except OSError as exc:
        raise AutoEditorError(f"Không chạy được FFmpeg source cleanup: {exc}") from exc

    frame_size = width * height * 3
    frame_count = 0
    scales: list[float] = []
    try:
        assert decoder.stdout is not None
        assert encoder.stdin is not None
        while True:
            payload = _read_exact(decoder.stdout, frame_size)
            if not payload:
                break
            if len(payload) != frame_size:
                raise AutoEditorError("FFmpeg trả về frame source cleanup không đầy đủ.")
            frame = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 3)
            cleaned, stats = reconstruct_flow_watermark(frame, geometry)
            encoder.stdin.write(cleaned.tobytes())
            frame_count += 1
            scales.append(stats["opacity_scale"])
        encoder.stdin.close()
        decode_code = decoder.wait()
        encode_code = encoder.wait()
    except (BrokenPipeError, OSError) as exc:
        decoder.kill()
        encoder.kill()
        raise AutoEditorError(f"Source-logo cleanup stream thất bại: {exc}") from exc

    decoder_error = (decoder.stderr.read() if decoder.stderr else b"").decode(
        "utf-8", errors="replace"
    ).strip()
    encoder_error = (encoder.stderr.read() if encoder.stderr else b"").decode(
        "utf-8", errors="replace"
    ).strip()
    if decode_code != 0 or encode_code != 0 or frame_count == 0:
        detail = encoder_error or decoder_error or "không có frame output"
        raise AutoEditorError(f"FFmpeg source-logo cleanup thất bại:\n{detail[-3000:]}")

    if diagnostics_path is not None:
        diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
        diagnostics_path.write_text(json.dumps({
            "strategy": "frequency_selective_reconstruct",
            "source": source.name,
            "frame_count": frame_count,
            "geometry": list(geometry),
            "opacity_scale_min": min(scales),
            "opacity_scale_max": max(scales),
            "deterministic": True,
            "global_crop": False,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
