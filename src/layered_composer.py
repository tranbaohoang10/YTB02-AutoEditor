from __future__ import annotations

import math
import subprocess
from dataclasses import replace
from pathlib import Path

from .config import AppConfig
from .layered_manifest import LayerItem, LayerState, LayeredSceneManifest, interpolate, smoothstep
from .media_qc import probe_video
from .models import AutoEditorError


_ANCHOR_FACTORS = {
    "top_left": (0.0, 0.0), "top_center": (0.5, 0.0), "top_right": (1.0, 0.0),
    "center_left": (0.0, 0.5), "center": (0.5, 0.5), "center_right": (1.0, 0.5),
    "bottom_left": (0.0, 1.0), "bottom_center": (0.5, 1.0), "bottom_right": (1.0, 1.0),
}


def _lerp_state(start: LayerState, end: LayerState, progress: float) -> LayerState:
    return LayerState(
        interpolate(start.x, end.x, progress),
        interpolate(start.y, end.y, progress),
        interpolate(start.scale, end.scale, progress),
        interpolate(start.rotation, end.rotation, progress),
        interpolate(start.opacity, end.opacity, progress),
    )


def layer_state_at(item: LayerItem, time: float, scene_duration: float) -> tuple[LayerState, float]:
    """Return animated state and horizontal/vertical reveal fraction."""
    target = item.state
    if time < item.start:
        return replace(target, opacity=0.0), 0.0
    raw = max(0.0, min(1.0, (time - item.start) / item.duration))
    progress = smoothstep(raw)
    start = target
    reveal = 1.0
    if item.enter == "slide_left_fade":
        start = replace(target, x=target.x - 180.0, opacity=0.0)
    elif item.enter == "slide_right_fade":
        start = replace(target, x=target.x + 180.0, opacity=0.0)
    elif item.enter == "slide_up_fade":
        start = replace(target, y=target.y - 140.0, opacity=0.0)
    elif item.enter == "slide_down_fade":
        start = replace(target, y=target.y + 140.0, opacity=0.0)
    elif item.enter == "pop_in":
        overshoot = 1.0 + 0.10 * math.sin(math.pi * raw)
        state = replace(target, scale=target.scale * (0.15 + 0.85 * progress) * overshoot, opacity=target.opacity * progress)
        return _apply_end_state(item, state, time, scene_duration), 1.0
    elif item.enter == "scale_in":
        start = replace(target, scale=target.scale * 0.35, opacity=0.0)
    elif item.enter == "stamp_in":
        start = replace(target, scale=target.scale * 1.65, rotation=target.rotation - 9.0, opacity=0.0)
    elif item.enter == "paper_drop":
        start = replace(target, y=target.y - 220.0, rotation=target.rotation - 7.0, opacity=0.0)
    elif item.enter == "slight_rotate_in":
        start = replace(target, rotation=target.rotation - 14.0, scale=target.scale * 0.92, opacity=0.0)
    elif item.enter in {"line_draw", "string_reveal"}:
        start = replace(target, opacity=target.opacity)
        reveal = progress
    elif item.enter == "highlight_flash":
        flash = min(1.0, progress * 1.8)
        start = replace(target, scale=target.scale * (0.92 + 0.08 * progress), opacity=target.opacity * flash)
    state = _lerp_state(start, target, progress)
    return _apply_end_state(item, state, time, scene_duration), reveal


def _apply_end_state(item: LayerItem, state: LayerState, time: float, scene_duration: float) -> LayerState:
    if item.end_state is None or time <= item.start + item.duration:
        return state
    span = max(0.001, scene_duration - item.start - item.duration)
    progress = (time - item.start - item.duration) / span
    return _lerp_state(item.state, item.end_state, progress)


def _cover(image, width: int, height: int):
    from PIL import Image
    ratio = max(width / image.width, height / image.height)
    size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    resized = image.resize(size, Image.Resampling.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height)).convert("RGBA")


def _render_layer(source, state: LayerState, reveal: float):
    from PIL import Image, ImageEnhance
    size = (max(1, round(source.width * state.scale)), max(1, round(source.height * state.scale)))
    layer = source.resize(size, Image.Resampling.LANCZOS)
    if reveal < 1.0:
        visible = max(1, round(layer.width * reveal))
        layer = layer.crop((0, 0, visible, layer.height))
    if state.rotation:
        layer = layer.rotate(-state.rotation, resample=Image.Resampling.BICUBIC, expand=True)
    if state.opacity < 1.0:
        alpha = layer.getchannel("A").point(lambda value: round(value * state.opacity))
        layer.putalpha(alpha)
    if state.opacity > 0.9 and reveal < 1.0:
        layer = ImageEnhance.Brightness(layer).enhance(1.02)
    return layer


def _apply_camera(frame, manifest: LayeredSceneManifest, time: float, duration: float):
    from PIL import Image
    camera = manifest.camera
    if camera.type == "none":
        return frame
    start = camera.start if camera.start is not None else manifest.build_complete
    span = camera.duration if camera.duration is not None else max(0.001, duration - start)
    progress = smoothstep((time - start) / span) if time >= start else 0.0
    target_zoom = camera.zoom
    if camera.type == "push_in" and abs(target_zoom - 1.0) < 0.0001:
        target_zoom = 1.04
    if camera.type == "push_out":
        initial_zoom = target_zoom if abs(target_zoom - 1.0) >= 0.0001 else 1.04
        zoom = interpolate(initial_zoom, 1.0, progress)
    else:
        zoom = interpolate(1.0, target_zoom, progress)
    offset_x = camera.x * progress
    offset_y = camera.y * progress
    scaled = frame.resize(
        (max(manifest.width, round(manifest.width * zoom)), max(manifest.height, round(manifest.height * zoom))),
        Image.Resampling.LANCZOS,
    )
    left = round((scaled.width - manifest.width) / 2 + offset_x)
    top = round((scaled.height - manifest.height) / 2 + offset_y)
    left = max(0, min(scaled.width - manifest.width, left))
    top = max(0, min(scaled.height - manifest.height, top))
    return scaled.crop((left, top, left + manifest.width, top + manifest.height))


def compose_frame(manifest: LayeredSceneManifest, time: float, duration: float, images: dict[str, object]):
    frame = images[manifest.background].copy()
    for item in manifest.items:
        state, reveal = layer_state_at(item, time, duration)
        if state.opacity <= 0.0 or reveal <= 0.0:
            continue
        layer = _render_layer(images[item.file], state, reveal)
        fx, fy = _ANCHOR_FACTORS[item.anchor]
        position = (round(state.x - layer.width * fx), round(state.y - layer.height * fy))
        frame.alpha_composite(layer, position)
    return _apply_camera(frame, manifest, time, duration).convert("RGB")


def render_layered_scene(
    manifest: LayeredSceneManifest, destination: Path, duration: float,
    config: AppConfig, *, validate_output: bool = True,
) -> None:
    if duration <= 0:
        raise AutoEditorError("Layered scene duration phải > 0.")
    if (manifest.width, manifest.height) != (config.video.width, config.video.height):
        raise AutoEditorError(
            f"Layered canvas phải là {config.video.width}x{config.video.height}."
        )
    try:
        from PIL import Image
    except ImportError as exc:
        raise AutoEditorError("Thiếu Pillow. Hãy chạy SETUP.bat.") from exc
    images: dict[str, object] = {}
    try:
        with Image.open(manifest.directory / manifest.background) as source:
            images[manifest.background] = _cover(source.convert("RGBA"), manifest.width, manifest.height)
        for item in manifest.items:
            if item.file not in images:
                with Image.open(manifest.directory / item.file) as source:
                    images[item.file] = source.convert("RGBA")
    except OSError as exc:
        raise AutoEditorError(f"Không decode được layered asset: {exc}") from exc
    frames = max(1, math.ceil(duration * config.video.fps))
    destination.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale={manifest.width}:{manifest.height}:in_range=full:out_range=limited,"
        "format=yuv420p,setparams=range=tv"
    )
    command = [
        config.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size",
        f"{manifest.width}x{manifest.height}", "-framerate", str(config.video.fps),
        "-i", "-", "-an", "-vf", vf, "-frames:v", str(frames),
        "-c:v", config.video.codec, "-crf", str(config.video.crf),
        "-preset", config.video.preset, "-pix_fmt", "yuv420p", "-color_range", "tv",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-x264-params", "range=limited:colorprim=bt709:transfer=bt709:colormatrix=bt709",
        "-r", str(config.video.fps), "-video_track_timescale", "90000", str(destination),
    ]
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        assert process.stdin is not None
        for frame_number in range(frames):
            frame_time = min(duration, frame_number / config.video.fps)
            process.stdin.write(compose_frame(manifest, frame_time, duration, images).tobytes())
        process.stdin.close()
        stderr = process.stderr.read() if process.stderr is not None else b""
        if process.stderr is not None:
            process.stderr.close()
        return_code = process.wait()
    except (OSError, BrokenPipeError) as exc:
        raise AutoEditorError(f"Không render được layered scene: {exc}") from exc
    if return_code != 0:
        detail = stderr.decode("utf-8", errors="replace")[-3000:]
        raise AutoEditorError(f"FFmpeg thất bại khi encode layered scene:\n{detail}")
    if validate_output:
        info = probe_video(destination, config.ffprobe)
        expected = config.video
        if (info["width"], info["height"]) != (expected.width, expected.height):
            raise AutoEditorError("Layered output sai resolution.")
        if info.get("codec_name") not in {"h264", "avc1"}:
            raise AutoEditorError(f"Layered output sai codec: {info.get('codec_name')}.")
        if info.get("pix_fmt") != "yuv420p" or info.get("color_range") != "tv":
            raise AutoEditorError(
                f"Layered output sai pixel format/range: {info.get('pix_fmt')}/{info.get('color_range')}."
            )
        if abs(float(info["fps"]) - expected.fps) > 0.01:
            raise AutoEditorError(f"Layered output sai FPS: {info['fps']}.")
        if abs(float(info["duration"]) - duration) > 1 / expected.fps + 0.02:
            raise AutoEditorError(
                f"Layered output sai duration: {info['duration']:.3f}s, cần {duration:.3f}s."
            )
