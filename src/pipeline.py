from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from .config import AppConfig, load_config
from .ffmpeg_utils import probe_duration, require_executable
from .models import AutoEditorError, Script, TimelineEntry
from .script_loader import load_script
from .subtitles import create_cues, write_ass, write_srt
from .timing import build_timeline
from .tts_bridge import generate_narration
from .video_builder import (
    concat_audio_scenes,
    concat_video_scenes,
    prepare_video_scene,
    render_final_video,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _clean_work_directory(work_dir: Path) -> tuple[Path, Path]:
    audio_dir = work_dir / "audio"
    scenes_dir = work_dir / "scenes"
    for directory in (audio_dir, scenes_dir):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)
    for filename in ("tts_manifest.json", "video_concat.txt", "audio_concat.txt", "gap.wav", "joined_video.mp4"):
        path = work_dir / filename
        if path.is_file():
            path.unlink()
    return audio_dir, scenes_dir


def _display_dry_run(script: Script, videos_dir: Path) -> None:
    print(f"Title: {script.title or '(không có)'}")
    print(f"Language: {script.language} | Voice: {script.voice} | Speed: {script.speed}")
    print(f"Scenes: {len(script.scenes)}")
    for scene in script.scenes:
        print(f"  {scene.id:03d} | {videos_dir / scene.video} | {scene.text}")
    print("DRY RUN OK - không tạo voice và không render video.")


def _prepare_scenes(
    timeline: tuple[TimelineEntry, ...], videos_dir: Path,
    scenes_dir: Path, config: AppConfig,
) -> list[Path]:
    results: list[Path] = []
    gap = config.audio.gap_ms / 1000.0
    for index, entry in enumerate(timeline):
        destination = scenes_dir / f"scene_{entry.scene.id:03d}.mp4"
        target_duration = entry.duration + (gap if index < len(timeline) - 1 else 0.0)
        print(f"       Scene {entry.scene.id:02d} video -> {target_duration:.2f} sec")
        prepare_video_scene(
            videos_dir / entry.scene.video, destination, target_duration, config
        )
        results.append(destination)
    return results


def run_pipeline(script_path: Path, config_path: Path, dry_run: bool = False) -> Path | None:
    print("[1/7] Loading project")
    config = load_config(config_path)
    videos_dir = PROJECT_ROOT / "input" / "videos"
    output_dir = PROJECT_ROOT / "output"
    work_dir = PROJECT_ROOT / "work"
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    print("[2/7] Validating script and videos")
    script = load_script(script_path, videos_dir)
    if dry_run:
        _display_dry_run(script, videos_dir)
        return None

    require_executable(config.ffmpeg, "FFmpeg")
    require_executable(config.ffprobe, "ffprobe")
    if not config.kokoro_python.is_file():
        raise AutoEditorError(f"Không tìm thấy Kokoro Python: {config.kokoro_python}")
    audio_dir, scenes_dir = _clean_work_directory(work_dir)

    print("[3/7] Generating narration")
    generate_narration(
        script, config.kokoro_python, PROJECT_ROOT / "src" / "kokoro_worker.py",
        audio_dir, work_dir, config.audio.sample_rate,
    )
    timeline = build_timeline(
        script.scenes, audio_dir,
        lambda path: probe_duration(path, config.ffprobe), config.audio.gap_ms,
    )
    for entry in timeline:
        print(f"       Scene {entry.scene.id:02d} ... {entry.duration:.2f} sec")

    print("[4/7] Building timeline")
    total = timeline[-1].end
    print(f"       Total narration timeline: {total:.2f} sec")

    print("[5/7] Preparing video scenes")
    prepared = _prepare_scenes(timeline, videos_dir, scenes_dir, config)
    joined_video = work_dir / "joined_video.mp4"
    concat_video_scenes(prepared, joined_video, config, work_dir)
    voice_path = output_dir / "voice.wav"
    concat_audio_scenes([entry.audio_path for entry in timeline], voice_path, config, work_dir)

    print("[6/7] Creating subtitles")
    cues = create_cues(timeline, config.subtitles)
    srt_path = output_dir / "subtitles.srt"
    ass_path = output_dir / "subtitles.ass"
    write_srt(cues, srt_path)
    write_ass(cues, ass_path, config.subtitles, config.video.width, config.video.height)

    print("[7/7] Rendering FINAL_VIDEO.mp4")
    final_path = output_dir / "FINAL_VIDEO.mp4"
    temporary = output_dir / "FINAL_VIDEO.building.mp4"
    if temporary.is_file():
        temporary.unlink()
    render_final_video(joined_video, voice_path, ass_path, temporary, config)
    if not temporary.is_file() or temporary.stat().st_size == 0:
        raise AutoEditorError("FFmpeg không tạo được video cuối hợp lệ.")
    os.replace(temporary, final_path)
    print("\nDONE")
    return final_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YTB02 AutoEditor local video builder")
    parser.add_argument(
        "--script", type=Path, default=PROJECT_ROOT / "input" / "script.json",
        help="Đường dẫn script JSON (mặc định: input/script.json)",
    )
    parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "config.json",
        help="Đường dẫn config JSON",
    )
    parser.add_argument("--dry-run", action="store_true", help="Chỉ validate, không TTS/render")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    args = _parser().parse_args(argv)
    try:
        result = run_pipeline(args.script.resolve(), args.config.resolve(), args.dry_run)
        if result:
            print(f"Video: {result}")
        return 0
    except AutoEditorError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nĐã hủy theo yêu cầu người dùng.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
