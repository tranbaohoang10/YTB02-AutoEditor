from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any, Sequence

from .models import AutoEditorError


def static_run_metrics(
    motion_flags: Sequence[bool], frame_duration_ms: float,
) -> tuple[float, float]:
    """Return longest and leading static runs without treating codec noise as motion."""
    longest = 0
    current = 0
    leading = 0
    still_leading = True
    for moving in motion_flags:
        if moving:
            current = 0
            still_leading = False
            continue
        current += 1
        longest = max(longest, current)
        if still_leading:
            leading += 1
    return longest * frame_duration_ms, leading * frame_duration_ms


def _decode_analysis_frames(
    video_path: Path, ffmpeg: str, fps: int,
    *, width: int = 160, height: int = 72,
) -> tuple[bytes, int]:
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(video_path),
        "-map", "0:v:0", "-an", "-vf",
        f"scale={width}:90,crop={width}:{height}:0:0,format=gray,fps={fps}",
        "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ]
    try:
        result = subprocess.run(command, capture_output=True)
    except OSError as exc:
        raise AutoEditorError(f"Không chạy được FFmpeg visual continuity: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace")[-2000:]
        raise AutoEditorError(f"FFmpeg không decode được frame continuity: {detail}")
    frame_size = width * height
    if not result.stdout or len(result.stdout) % frame_size:
        raise AutoEditorError("Raw frame continuity bị rỗng hoặc sai kích thước.")
    return result.stdout, frame_size


def _frame_delta(raw: bytes, frame_size: int, frame_index: int) -> float:
    frame_count = len(raw) // frame_size
    if frame_index <= 0 or frame_index >= frame_count:
        return 0.0
    previous_start = (frame_index - 1) * frame_size
    current_start = frame_index * frame_size
    previous = memoryview(raw)[previous_start:previous_start + frame_size]
    current = memoryview(raw)[current_start:current_start + frame_size]
    return sum(abs(left - right) for left, right in zip(previous, current)) / frame_size


def _freeze_map(payload: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    if not payload:
        return {}
    return {
        int(item["scene_id"]): item
        for item in payload.get("scenes", [])
        if isinstance(item, dict) and "scene_id" in item
    }

def analyze_visual_continuity(
    video_path: Path, transitions_path: Path, *, ffmpeg: str = "ffmpeg",
    fps: int = 30, motion_threshold: float = 0.75,
    freeze_path: Path | None = None,
) -> dict[str, Any]:
    if fps <= 0 or motion_threshold <= 0:
        raise AutoEditorError("FPS và motion threshold phải > 0.")
    try:
        schedule = json.loads(transitions_path.read_text(encoding="utf-8-sig"))
        freeze_payload = (
            json.loads(freeze_path.read_text(encoding="utf-8-sig"))
            if freeze_path is not None and freeze_path.is_file() else None
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise AutoEditorError(f"Không đọc được continuity diagnostics: {exc}") from exc
    raw, frame_size = _decode_analysis_frames(video_path, ffmpeg, fps)
    frame_count = len(raw) // frame_size
    frame_ms = 1000.0 / fps
    freezes = _freeze_map(freeze_payload)
    delta_cache: dict[int, float] = {}

    def delta(index: int) -> float:
        if index not in delta_cache:
            delta_cache[index] = _frame_delta(raw, frame_size, index)
        return delta_cache[index]

    records: list[dict[str, Any]] = []
    for item in schedule.get("boundaries", []):
        pause_start = float(item["pause_start"])
        pause_end = float(item["pause_end"])
        start_frame = max(1, math.ceil(pause_start * fps - 1e-9))
        end_frame = min(frame_count - 1, round(pause_end * fps))
        indices = list(range(start_frame, max(start_frame, end_frame) + 1))
        deltas = [delta(index) for index in indices]
        flags = [value >= motion_threshold for value in deltas]
        static_dead_zone_ms, static_before_ms = static_run_metrics(flags, frame_ms)
        visual_start = item.get("visual_start")
        visual_end = item.get("visual_end")
        if visual_end is None and visual_start is not None:
            visual_end = float(visual_start) + float(item.get("visual_duration_ms", 0)) / 1000.0
        transition_motion_ms = sum(
            frame_ms for index, moving in zip(indices, flags)
            if moving and visual_start is not None and visual_end is not None
            and float(visual_start) < index / fps <= float(visual_end) + 1e-9
        )
        reference_time = (
            float(visual_start) if visual_start is not None else pause_end
        )
        reference_frame = min(end_frame, max(start_frame, round(reference_time * fps)))
        previous_indices = range(max(start_frame, reference_frame - 3), reference_frame)
        previous_deltas = [delta(index) for index in previous_indices]
        previous_static = bool(previous_deltas) and all(
            value < motion_threshold for value in previous_deltas
        )
        freeze = freezes.get(int(item["from_scene"]), {})
        records.append({
            "boundary_index": int(item["boundary_index"]),
            "scene_from": int(item["from_scene"]),
            "scene_to": int(item["to_scene"]),
            "last_spoken_word_end": round(pause_start, 6),
            "next_spoken_word_start": round(pause_end, 6),
            "available_narration_pause_ms": round((pause_end - pause_start) * 1000),
            "visual_cut_timestamp": round(round(pause_end * fps) / fps, 6),
            "pre_roll_start": item.get("bridge_start"),
            "transition_start": visual_start,
            "transition_end": visual_end,
            "transition_type": item.get("effect", "none"),
            "transition_sfx": item.get("sfx"),
            "freeze_tail_ms": round(float(freeze.get("freeze_duration", 0.0)) * 1000),
            "freeze_tail_masked": bool(freeze.get("tail_motion_masked", False)),
            "previous_frame_effectively_static": previous_static,
            "static_before_ms": round(static_before_ms),
            "transition_motion_ms": round(transition_motion_ms),
            "settle_ms": round(float(item.get("settle_ms", 0.0))),
            "static_dead_zone_ms": round(static_dead_zone_ms),
            "mean_frame_delta": round(sum(deltas) / len(deltas), 6) if deltas else 0.0,
            "max_frame_delta": round(max(deltas), 6) if deltas else 0.0,
            "reason": item.get("reason", ""),
        })

    eligible = [
        item for item in records if item["available_narration_pause_ms"] >= 250
    ]
    dead_zones = [float(item["static_dead_zone_ms"]) for item in eligible]
    effect_counts: dict[str, int] = {}
    for item in records:
        effect = str(item["transition_type"])
        effect_counts[effect] = effect_counts.get(effect, 0) + 1
    return {
        "source": str(video_path),
        "fps": fps,
        "motion_detector": {
            "method": "top-content grayscale mean absolute frame delta",
            "analysis_size": "160x72",
            "threshold": motion_threshold,
            "subtitle_watermark_region_excluded": True,
        },
        "scene_boundary_count": len(records),
        "eligible_pause_count": len(eligible),
        "effect_counts": effect_counts,
        "eligible_static_dead_zone_average_ms": (
            round(sum(dead_zones) / len(dead_zones), 3) if dead_zones else 0.0
        ),
        "eligible_static_dead_zone_max_ms": round(max(dead_zones), 3) if dead_zones else 0.0,
        "eligible_over_200ms": sum(value > 200 for value in dead_zones),
        "eligible_at_or_below_120ms": sum(value <= 120 for value in dead_zones),
        "boundaries": records,
    }
