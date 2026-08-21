from __future__ import annotations

import math
from pathlib import Path

from .config import AppConfig
from .ffmpeg_utils import run_media_command
from .media_qc import probe_video
from .models import AutoEditorError


MOTION_PRESETS = (
    "slow_push_in", "pan_right", "slow_pull_out", "pan_left",
    "pan_up", "pan_down", "drift_subtle", "static",
)


def automatic_motion(scene_id: int) -> str:
    if scene_id < 1:
        raise AutoEditorError("Scene id phải >= 1 để chọn motion deterministic.")
    return MOTION_PRESETS[(scene_id - 1) % len(MOTION_PRESETS)]


def _zoompan_filter(preset: str, width: int, height: int, fps: int, frames: int) -> str:
    fill = (
        f"scale={math.ceil(width * 1.08 / 2) * 2}:{math.ceil(height * 1.08 / 2) * 2}:"
        "force_original_aspect_ratio=increase"
    )
    denominator = max(1, frames - 1)
    progress = f"on/{denominator}"
    limited_yuv420p = (
        f"scale={width}:{height}:in_range=auto:out_range=limited,"
        "format=yuv420p,setparams=range=tv"
    )
    if preset == "static":
        return (
            f"{fill},crop={width}:{height}:(iw-ow)/2:(ih-oh)/2,fps={fps},"
            f"{limited_yuv420p}"
        )
    if preset == "slow_push_in":
        z, x, y = f"1+0.045*{progress}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif preset == "slow_pull_out":
        z, x, y = f"1.045-0.045*{progress}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif preset == "pan_left":
        z, x, y = "1.045", f"(iw-iw/zoom)*(1-{progress})", "ih/2-(ih/zoom/2)"
    elif preset == "pan_right":
        z, x, y = "1.045", f"(iw-iw/zoom)*{progress}", "ih/2-(ih/zoom/2)"
    elif preset == "pan_up":
        z, x, y = "1.045", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*(1-{progress})"
    elif preset == "pan_down":
        z, x, y = "1.045", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*{progress}"
    elif preset == "drift_subtle":
        z, x, y = f"1.015+0.015*{progress}", f"(iw-iw/zoom)*{progress}", f"(ih-ih/zoom)*(1-{progress})"
    else:
        raise AutoEditorError(f"Motion preset không hỗ trợ: {preset}")
    return (
        f"{fill},zoompan=z='{z}':x='{x}':y='{y}':d=1:"
        f"s={width}x{height}:fps={fps},{limited_yuv420p}"
    )


def prepare_image_scene(
    source: Path, destination: Path, duration: float,
    config: AppConfig, preset: str, *, validate_output: bool = True,
) -> None:
    if duration <= 0:
        raise AutoEditorError("Image motion duration phải > 0.")
    if preset == "auto":
        raise AutoEditorError("Motion 'auto' phải được resolve theo scene id trước khi render.")
    video = config.video
    frames = max(1, math.ceil(duration * video.fps))
    vf = _zoompan_filter(preset, video.width, video.height, video.fps, frames)
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        config.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-loop", "1", "-framerate", str(video.fps), "-i", str(source),
        "-an", "-vf", vf, "-t", f"{duration:.6f}",
        "-c:v", video.codec, "-crf", str(video.crf), "-preset", video.preset,
        "-pix_fmt", "yuv420p", "-color_range", "tv", "-r", str(video.fps),
        "-video_track_timescale", "90000", str(destination),
    ]
    run_media_command(command, f"tạo local image motion cho {source.name}")
    if validate_output:
        info = probe_video(destination, config.ffprobe)
        if info["width"] != video.width or info["height"] != video.height:
            raise AutoEditorError(f"Motion output sai resolution: {info['width']}x{info['height']}.")
        if info.get("codec_name") not in {"h264", "avc1"}:
            raise AutoEditorError(f"Motion output sai codec: {info.get('codec_name')}.")
        if info.get("pix_fmt") != "yuv420p":
            raise AutoEditorError(f"Motion output sai pixel format: {info.get('pix_fmt')}.")
        if info.get("color_range") != "tv":
            raise AutoEditorError(f"Motion output sai color range: {info.get('color_range')}.")
        if abs(float(info["fps"]) - video.fps) > 0.01:
            raise AutoEditorError(f"Motion output sai FPS: {info['fps']}.")
        if abs(float(info["duration"]) - duration) > 1 / video.fps + 0.02:
            raise AutoEditorError(
                f"Motion output sai duration: {info['duration']:.3f}s, cần {duration:.3f}s."
            )
