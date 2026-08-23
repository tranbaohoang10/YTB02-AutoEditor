from __future__ import annotations

import math
import os
import sys
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .config import AppConfig
from .ffmpeg_utils import ffmpeg_filter_path, run_media_command, write_concat_file
from .layered_manifest import SceneTransition
from .models import AutoEditorError


_XFADE_TRANSITIONS = {
    "crossfade": "fade",
    "paper_wipe": "wipeleft",
    "push_left": "slideleft",
    "push_right": "slideright",
    "zoom_fade": "zoomin",
    "none": "fade",
}


@dataclass(frozen=True)
class SourceAudioClip:
    path: Path
    start: float
    duration: float


def trim_narration_padding(
    audio_paths: Sequence[Path], config: AppConfig,
) -> None:
    """Trim only generated leading/trailing padding; internal pauses stay untouched."""
    for audio_path in audio_paths:
        temporary = audio_path.with_suffix(".trimmed.wav")
        try:
            with wave.open(str(audio_path), "rb") as source:
                parameters = source.getparams()
                frames = source.readframes(source.getnframes())
            if parameters.nchannels != 1 or parameters.sampwidth != 2:
                raise AutoEditorError(
                    f"Narration WAV phải là mono PCM 16-bit: {audio_path.name}"
                )
            samples = array("h")
            samples.frombytes(frames)
            if sys.byteorder != "little":
                samples.byteswap()
            window = max(1, parameters.framerate // 100)
            threshold = 32767.0 * 10 ** (
                config.audio.narration_silence_threshold_db / 20.0
            )
            active: list[int] = []
            for start in range(0, len(samples), window):
                chunk = samples[start:start + window]
                rms = math.sqrt(
                    sum(sample * sample for sample in chunk) / max(1, len(chunk))
                )
                if rms > threshold:
                    active.append(start)
            if not active:
                raise AutoEditorError(f"Narration WAV chỉ có silence: {audio_path.name}")
            keep = round(
                parameters.framerate * config.audio.narration_edge_silence_ms / 1000.0
            )
            first = max(0, active[0] - keep)
            last = min(len(samples), active[-1] + window + keep)
            trimmed = samples[first:last]
            if sys.byteorder != "little":
                trimmed.byteswap()
            with wave.open(str(temporary), "wb") as output:
                output.setparams(parameters)
                output.writeframes(trimmed.tobytes())
            os.replace(temporary, audio_path)
        finally:
            if temporary.is_file():
                temporary.unlink()


def build_source_audio_mix(
    clips: Sequence[SourceAudioClip], destination: Path,
    total_duration: float, config: AppConfig,
) -> bool:
    if not config.audio.preserve_source_audio or not clips:
        return False
    if total_duration <= 0 or any(clip.duration <= 0 or clip.start < 0 for clip in clips):
        raise AutoEditorError("Source-audio clip duration/start không hợp lệ.")
    command = [config.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for clip in clips:
        command.extend(["-i", str(clip.path)])
    filters: list[str] = []
    labels: list[str] = []
    for index, clip in enumerate(clips):
        fade = min(config.audio.source_audio_fade_ms / 1000.0, clip.duration / 2.0)
        fade_out_start = max(0.0, clip.duration - fade)
        delay_ms = round(clip.start * 1000.0)
        label = f"sfx{index}"
        labels.append(f"[{label}]")
        chain = (
            f"[{index}:a:0]atrim=start=0:duration={clip.duration:.6f},"
            "asetpts=PTS-STARTPTS,"
            f"aresample={config.audio.mix_sample_rate},"
            f"aformat=sample_fmts=fltp:sample_rates={config.audio.mix_sample_rate}:"
            "channel_layouts=stereo,"
            f"volume={config.audio.source_audio_gain_db:.3f}dB"
        )
        if fade > 0:
            chain += (
                f",afade=t=in:st=0:d={fade:.6f},"
                f"afade=t=out:st={fade_out_start:.6f}:d={fade:.6f}"
            )
        chain += f",adelay={delay_ms}:all=1[{label}]"
        filters.append(chain)
    if len(labels) == 1:
        base = labels[0]
    else:
        filters.append(
            f"{''.join(labels)}amix=inputs={len(labels)}:"
            "duration=longest:dropout_transition=0:normalize=0[sfxbase]"
        )
        base = "[sfxbase]"
    filters.append(
        f"{base}apad=whole_dur={total_duration:.6f},"
        f"atrim=duration={total_duration:.6f}[sfx]"
    )
    command.extend([
        "-filter_complex", ";".join(filters), "-map", "[sfx]",
        "-ar", str(config.audio.mix_sample_rate), "-ac", "2",
        "-c:a", "pcm_s16le", str(destination),
    ])
    run_media_command(command, "tạo source-video SFX master")
    return True


def prepare_video_scene(
    source: Path, destination: Path, duration: float, config: AppConfig
) -> None:
    video = config.video
    vf = (
        f"scale={video.width}:{video.height}:force_original_aspect_ratio=decrease,"
        f"pad={video.width}:{video.height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={video.fps},"
        f"tpad=stop_mode=clone:stop_duration={duration:.6f},"
        f"trim=duration={duration:.6f},setpts=PTS-STARTPTS"
    )
    command = [
        config.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-map", "0:v:0", "-an", "-vf", vf,
        "-c:v", video.codec, "-crf", str(video.crf), "-preset", video.preset,
        "-pix_fmt", "yuv420p", "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-r", str(video.fps),
        "-video_track_timescale", "90000", str(destination),
    ]
    run_media_command(command, f"chuẩn bị clip {source.name}")


def concat_video_scenes(
    scene_paths: Sequence[Path], destination: Path, config: AppConfig, work_dir: Path
) -> None:
    concat_file = work_dir / "video_concat.txt"
    write_concat_file(scene_paths, concat_file)
    command = [
        config.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-map", "0:v:0", "-c", "copy", str(destination),
    ]
    run_media_command(command, "ghép các video scene")


def concat_video_scenes_with_transitions(
    scene_paths: Sequence[Path], durations: Sequence[float],
    transitions: Sequence[SceneTransition], destination: Path, config: AppConfig,
) -> None:
    if len(scene_paths) < 2:
        raise AutoEditorError("Cần ít nhất hai scene để tạo transition.")
    if len(durations) != len(scene_paths) or len(transitions) != len(scene_paths) - 1:
        raise AutoEditorError("Số duration/transition không khớp số scene.")
    if any(duration <= 0 for duration in durations):
        raise AutoEditorError("Duration scene phải > 0 khi ghép transition.")
    command = [config.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for path in scene_paths:
        command.extend(["-i", str(path)])
    filters: list[str] = []
    effective_durations: list[float] = []
    frame_duration = 1.0 / config.video.fps
    for index, duration in enumerate(durations):
        if index < len(transitions):
            transition = transitions[index]
            transition_duration = transition.duration if transition.type != "none" else frame_duration
            if transition_duration >= duration:
                raise AutoEditorError(
                    f"Transition scene {index + 1} phải ngắn hơn duration scene ({duration:.3f}s)."
                )
            effective_durations.append(transition_duration)
            tail = f",tpad=stop_mode=clone:stop_duration={transition_duration:.6f}"
        else:
            tail = ""
        filters.append(
            f"[{index}:v]trim=duration={duration:.6f},setpts=PTS-STARTPTS{tail},"
            f"fps={config.video.fps},format=yuv420p,setparams=range=tv[v{index}]"
        )
    previous = "v0"
    offset = durations[0]
    for index, transition in enumerate(transitions, 1):
        transition_duration = effective_durations[index - 1]
        name = _XFADE_TRANSITIONS[transition.type]
        output = f"x{index}"
        filters.append(
            f"[{previous}][v{index}]xfade=transition={name}:"
            f"duration={transition_duration:.6f}:offset={offset:.6f}[{output}]"
        )
        previous = output
        offset += durations[index]
    command.extend([
        "-filter_complex", ";".join(filters), "-map", f"[{previous}]", "-an",
        "-c:v", config.video.codec, "-crf", str(config.video.crf),
        "-preset", config.video.preset, "-pix_fmt", "yuv420p", "-color_range", "tv",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-x264-params", "range=limited:colorprim=bt709:transfer=bt709:colormatrix=bt709",
        "-r", str(config.video.fps), "-video_track_timescale", "90000", str(destination),
    ])
    run_media_command(command, "ghép các scene với transition")


def concat_audio_scenes(
    audio_paths: Sequence[Path], destination: Path, config: AppConfig, work_dir: Path
) -> None:
    sources: list[Path] = []
    silence_path = work_dir / "gap.wav"
    if config.audio.gap_ms > 0 and len(audio_paths) > 1:
        gap_seconds = config.audio.gap_ms / 1000.0
        command = [
            config.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i",
            f"anullsrc=r={config.audio.sample_rate}:cl=mono",
            "-t", f"{gap_seconds:.6f}", "-c:a", "pcm_s16le", str(silence_path),
        ]
        run_media_command(command, "tạo khoảng lặng giữa scene")
    for index, audio_path in enumerate(audio_paths):
        sources.append(audio_path)
        if silence_path.is_file() and index < len(audio_paths) - 1:
            sources.append(silence_path)
    concat_file = work_dir / "audio_concat.txt"
    write_concat_file(sources, concat_file)
    command = [
        config.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
    ]
    if config.audio.normalize_loudness:
        command.extend([
            "-af",
            (
                f"loudnorm=I={config.audio.target_lufs}:"
                f"TP={config.audio.true_peak_db}:LRA={config.audio.lra}"
            ),
        ])
    command.extend([
        "-ar", str(config.audio.sample_rate), "-ac", "1",
        "-c:a", "pcm_s16le", str(destination),
    ])
    run_media_command(command, "ghép narration")


def render_final_video(
    video_path: Path, audio_path: Path, ass_path: Path,
    temporary_output: Path, config: AppConfig,
    source_audio_path: Path | None = None,
) -> None:
    video = config.video
    subtitle_filter = (
        f"ass=filename='{ffmpeg_filter_path(ass_path)}',"
        "format=yuv420p,setparams=range=tv"
    )
    command = [
        config.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_path), "-i", str(audio_path),
    ]
    if source_audio_path is not None:
        command.extend(["-i", str(source_audio_path)])
        command.extend([
            "-filter_complex",
            (
                f"[1:a:0]aresample={config.audio.mix_sample_rate},"
                "aformat=sample_fmts=fltp:channel_layouts=mono,"
                "pan=stereo|c0=0.707107*c0|c1=0.707107*c0[voice];"
                f"[2:a:0]aresample={config.audio.mix_sample_rate},"
                f"aformat=sample_fmts=fltp:sample_rates={config.audio.mix_sample_rate}:"
                "channel_layouts=stereo[sfx];"
                "[voice][sfx]amix=inputs=2:duration=first:"
                "dropout_transition=0:normalize=0,"
                f"loudnorm=I={config.audio.target_lufs}:"
                f"TP={config.audio.true_peak_db}:LRA={config.audio.lra}[mixed]"
            ),
            "-map", "0:v:0", "-map", "[mixed]",
        ])
    else:
        command.extend([
            "-map", "0:v:0", "-map", "1:a:0",
            "-af",
            (
                f"aresample={config.audio.mix_sample_rate},"
                "aformat=sample_fmts=fltp:channel_layouts=mono,"
                "pan=stereo|c0=0.707107*c0|c1=0.707107*c0"
            ),
        ])
    command.extend([
        "-vf", subtitle_filter,
        "-c:v", video.codec, "-crf", str(video.crf), "-preset", video.preset,
        "-pix_fmt", "yuv420p", "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709",
        "-x264-params", "range=limited:colorprim=bt709:transfer=bt709:colormatrix=bt709",
        "-r", str(video.fps),
        "-ar", str(config.audio.mix_sample_rate), "-ac", "2",
        "-c:a", "aac", "-b:a", config.audio.aac_bitrate,
        "-movflags", "+faststart", "-shortest", str(temporary_output),
    ])
    run_media_command(command, "burn subtitle và render video cuối")
