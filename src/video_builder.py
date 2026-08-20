from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .config import AppConfig
from .ffmpeg_utils import ffmpeg_filter_path, run_media_command, write_concat_file


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
        "-pix_fmt", "yuv420p", "-r", str(video.fps),
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
        "-ar", str(config.audio.sample_rate), "-ac", "1",
        "-c:a", "pcm_s16le", str(destination),
    ]
    run_media_command(command, "ghép narration")


def render_final_video(
    video_path: Path, audio_path: Path, ass_path: Path,
    temporary_output: Path, config: AppConfig,
) -> None:
    video = config.video
    subtitle_filter = f"ass=filename='{ffmpeg_filter_path(ass_path)}'"
    command = [
        config.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_path), "-i", str(audio_path),
        "-map", "0:v:0", "-map", "1:a:0", "-vf", subtitle_filter,
        "-c:v", video.codec, "-crf", str(video.crf), "-preset", video.preset,
        "-pix_fmt", "yuv420p", "-r", str(video.fps),
        "-c:a", "aac", "-b:a", config.audio.aac_bitrate,
        "-movflags", "+faststart", "-shortest", str(temporary_output),
    ]
    run_media_command(command, "burn subtitle và render video cuối")
