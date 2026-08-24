from __future__ import annotations

import json
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
from .narration import PauseCompressionReport, compress_smart_pauses


_XFADE_TRANSITIONS = {
    "crossfade": "fade",
    "paper_swipe": "wipeleft",
    "paper_slide": "slideleft",
    "paper_wipe": "wiperight",
    "collage_push": "slideright",
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
    audio_paths: Sequence[Path], config: AppConfig, *, edge_silence_ms: int | None = None,
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
            keep_ms = (
                config.audio.narration_edge_silence_ms
                if edge_silence_ms is None else edge_silence_ms
            )
            keep = round(parameters.framerate * keep_ms / 1000.0)
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


def process_narration_audio(
    audio_paths: Sequence[Path], config: AppConfig,
    diagnostics_path: Path | None = None,
    *, language: str = "en", aligned_words: Sequence[Sequence[object]] = (),
) -> tuple[PauseCompressionReport, ...]:
    """Compress eligible internal pauses after the caller trims chunk edges."""
    if aligned_words and len(aligned_words) != len(audio_paths):
        raise AutoEditorError("Số pause-context alignment không khớp narration chunks.")
    reports: tuple[PauseCompressionReport, ...] = ()
    if config.audio.smart_pause_compression:
        reports = tuple(
            compress_smart_pauses(
                audio_path, config.audio, language,
                aligned_words[index] if aligned_words else (),
            )
            for index, audio_path in enumerate(audio_paths)
        )
    if diagnostics_path is not None:
        diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
        diagnostics_path.write_text(
            json.dumps(
                {
                    "enabled": config.audio.smart_pause_compression,
                    "files": [report.as_dict() for report in reports],
                    "total_removed_seconds": round(
                        sum(report.removed_duration for report in reports), 6
                    ),
                    "compressed_pause_count": sum(
                        report.compressed_pause_count for report in reports
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return reports


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
            if transition_duration >= duration or transition_duration >= durations[index + 1]:
                raise AutoEditorError(
                    f"Transition scene {index + 1} phải ngắn hơn cả hai scene kề nhau."
                )
            effective_durations.append(transition_duration)
        incoming_pad = effective_durations[index - 1] if index > 0 else 0.0
        tail = (
            f",tpad=stop_mode=clone:stop_duration={incoming_pad:.6f}"
            if incoming_pad > 0 else ""
        )
        filters.append(
            f"[{index}:v]trim=duration={duration:.6f},setpts=PTS-STARTPTS{tail},"
            f"fps={config.video.fps},format=yuv420p,setparams=range=tv[v{index}]"
        )
    previous = "v0"
    boundary = durations[0]
    for index, transition in enumerate(transitions, 1):
        transition_duration = effective_durations[index - 1]
        name = _XFADE_TRANSITIONS[transition.type]
        output = f"x{index}"
        offset = boundary - transition_duration
        filters.append(
            f"[{previous}][v{index}]xfade=transition={name}:"
            f"duration={transition_duration:.6f}:offset={offset:.6f}[{output}]"
        )
        previous = output
        boundary += durations[index]
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
    audio_paths: Sequence[Path], destination: Path, config: AppConfig, work_dir: Path,
    *, gap_ms: int | None = None,
) -> None:
    sources: list[Path] = []
    silence_path = work_dir / "gap.wav"
    selected_gap_ms = config.audio.gap_ms if gap_ms is None else gap_ms
    if selected_gap_ms < 0:
        raise AutoEditorError("Narration join gap không được âm.")
    if selected_gap_ms > 0 and len(audio_paths) > 1:
        gap_seconds = selected_gap_ms / 1000.0
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
    transition_audio_path: Path | None = None,
) -> None:
    video = config.video
    video_filters = [f"ass=filename='{ffmpeg_filter_path(ass_path)}'"]
    if config.watermark.enabled:
        font = config.watermark.font.replace("\\", r"\\").replace("'", r"\'")
        text = config.watermark.text.replace("\\", r"\\").replace("'", r"\'")
        font_option = (
            f"fontfile='{ffmpeg_filter_path(config.watermark.font_file)}'"
            if config.watermark.font_file is not None else f"font='{font}'"
        )
        video_filters.append(
            "drawtext="
            f"{font_option}:text='{text}':"
            f"fontcolor=white@{config.watermark.opacity:.3f}:"
            f"fontsize={config.watermark.font_size}:"
            f"x=w-text_w-{config.watermark.margin_right}:"
            f"y=h-text_h-{config.watermark.margin_bottom}:"
            "shadowcolor=black@0.650:"
            f"shadowx={config.watermark.shadow_x}:shadowy={config.watermark.shadow_y}"
        )
    video_filters.extend(["format=yuv420p", "setparams=range=tv"])
    final_video_filter = ",".join(video_filters)
    command = [
        config.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_path), "-i", str(audio_path),
    ]
    extra_audio: list[tuple[Path, str]] = []
    if source_audio_path is not None:
        extra_audio.append((source_audio_path, "sfx"))
    if transition_audio_path is not None:
        extra_audio.append((transition_audio_path, "transition"))
    if extra_audio:
        for path, _ in extra_audio:
            command.extend(["-i", str(path)])
        audio_filters = [
            f"[1:a:0]aresample={config.audio.mix_sample_rate},"
            "aformat=sample_fmts=fltp:channel_layouts=mono,"
            "pan=stereo|c0=0.707107*c0|c1=0.707107*c0[voice]"
        ]
        mix_labels = ["[voice]"]
        for input_index, (_, label) in enumerate(extra_audio, 2):
            audio_filters.append(
                f"[{input_index}:a:0]aresample={config.audio.mix_sample_rate},"
                f"aformat=sample_fmts=fltp:sample_rates={config.audio.mix_sample_rate}:"
                f"channel_layouts=stereo[{label}]"
            )
            mix_labels.append(f"[{label}]")
        audio_filters.append(
            f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=first:"
            "dropout_transition=0:normalize=0,"
            f"loudnorm=I={config.audio.target_lufs}:"
            f"TP={config.audio.true_peak_db}:LRA={config.audio.lra}[mixed]"
        )
        command.extend([
            "-filter_complex", ";".join(audio_filters),
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
        "-vf", final_video_filter,
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
