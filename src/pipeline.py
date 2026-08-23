from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from .alignment import align_timeline
from .config import AppConfig, load_config
from .ffmpeg_utils import probe_duration, require_executable
from .image_assets import VisualAsset, resolve_visual_assets
from .layered_composer import render_layered_scene
from .layered_manifest import SceneTransition, load_layered_manifest
from .motion_service import render_image_motion
from .motion_providers.ai_image_to_video import create_ai_motion_provider
from .models import AutoEditorError, Script, TimelineEntry
from .script_loader import load_script
from .subtitles import create_rolling_cues, write_ass, write_srt
from .timing import build_timeline
from .tts_bridge import generate_narration
from .video_builder import (
    concat_audio_scenes,
    concat_video_scenes,
    concat_video_scenes_with_transitions,
    prepare_video_scene,
    render_final_video,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FINAL_VIDEO_PATTERN = re.compile(r"FINAL_VIDEO_([0-9]+)\.mp4\Z")
FINAL_VIDEO_RESERVATION_ATTEMPTS = 100


def _existing_final_videos(output_dir: Path) -> list[tuple[int, Path]]:
    matches: list[tuple[int, Path]] = []
    for path in output_dir.iterdir():
        match = FINAL_VIDEO_PATTERN.fullmatch(path.name)
        if match and path.is_file():
            matches.append((int(match.group(1)), path))
    return matches


def reserve_final_video_path(output_dir: Path) -> Path:
    """Atomically reserve the next max-plus-one final-video filename."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(FINAL_VIDEO_RESERVATION_ATTEMPTS):
        existing = _existing_final_videos(output_dir)
        next_number = max((number for number, _ in existing), default=0) + 1
        candidate = output_dir / f"FINAL_VIDEO_{next_number}.mp4"
        try:
            descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        os.close(descriptor)
        return candidate
    raise AutoEditorError(
        "Không thể giữ tên video final mới do có quá nhiều build đồng thời."
    )


def latest_final_video_path(output_dir: Path) -> Path:
    existing = _existing_final_videos(output_dir)
    if not existing:
        raise AutoEditorError(f"Không tìm thấy video final trong: {output_dir}")
    return max(existing, key=lambda item: (item[0], item[1].name))[1]


def atomic_replace_final(temporary: Path, final_path: Path) -> None:
    if not temporary.is_file() or temporary.stat().st_size == 0:
        raise AutoEditorError("FFmpeg không tạo được video cuối hợp lệ.")
    if not final_path.is_file() or final_path.stat().st_size != 0:
        raise AutoEditorError(f"Tên video final không còn được giữ an toàn: {final_path}")
    os.replace(temporary, final_path)


def _clean_work_directory(work_dir: Path) -> tuple[Path, Path, Path, Path]:
    audio_dir = work_dir / "audio"
    scenes_dir = work_dir / "scenes"
    motion_dir = work_dir / "motion"
    alignment_dir = work_dir / "alignment"
    for directory in (audio_dir, scenes_dir, motion_dir, alignment_dir):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)
    for filename in ("tts_manifest.json", "video_concat.txt", "audio_concat.txt", "gap.wav", "joined_video.mp4"):
        path = work_dir / filename
        if path.is_file():
            path.unlink()
    return audio_dir, scenes_dir, motion_dir, alignment_dir


def _display_dry_run(script: Script, videos_dir: Path, images_dir: Path) -> None:
    print(f"Title: {script.title or '(không có)'}")
    print(f"Language: {script.language} | Voice: {script.voice} | Speed: {script.speed}")
    print(f"Scenes: {len(script.scenes)}")
    for scene in script.scenes:
        if scene.assets:
            source = videos_dir.parent / "scenes" / scene.assets / "manifest.json"
        elif scene.image:
            source = images_dir / scene.image
        elif scene.video:
            source = videos_dir / scene.video
        else:
            source = Path(f"generated://scene_{scene.id:03d}.png")
        print(f"  {scene.id:03d} | {source} | {scene.text}")
    print("DRY RUN OK - không tạo voice và không render video.")


def _prepare_scenes(
    timeline: tuple[TimelineEntry, ...], assets: dict[int, VisualAsset],
    scenes_dir: Path, motion_dir: Path, config: AppConfig,
    motion_mode: str, *, ai_provider: Any = None, fallback_local: bool = False,
) -> list[Path]:
    results: list[Path] = []
    gap = config.audio.gap_ms / 1000.0
    for index, entry in enumerate(timeline):
        destination = scenes_dir / f"scene_{entry.scene.id:03d}.mp4"
        target_duration = entry.duration + (gap if index < len(timeline) - 1 else 0.0)
        asset = assets[entry.scene.id]
        print(f"       Scene {entry.scene.id:02d} {asset.kind} -> {target_duration:.2f} sec")
        if asset.kind == "video":
            prepare_video_scene(asset.path, destination, target_duration, config)
        elif asset.kind == "layered":
            manifest = load_layered_manifest(
                asset.path, expected_width=config.video.width,
                expected_height=config.video.height,
            )
            render_layered_scene(manifest, destination, target_duration, config)
        else:
            motion_output = motion_dir / f"scene_{entry.scene.id:03d}.mp4"
            render_image_motion(
                entry.scene, asset.path, motion_output, target_duration, config,
                motion_mode, ai_provider=ai_provider, fallback_local=fallback_local,
            )
            shutil.copy2(motion_output, destination)
        results.append(destination)
    return results


def run_pipeline(
    script_path: Path,
    config_path: Path,
    dry_run: bool = False,
    *,
    generate_images_only: bool = False,
    force_images: bool = False,
    motion_mode: str | None = None,
    image_provider: Any = None,
    ai_motion_provider: Any = None,
) -> Path | None:
    print("[1/10] Loading project")
    config = load_config(config_path)
    videos_dir = PROJECT_ROOT / "input" / "videos"
    images_dir = PROJECT_ROOT / "input" / "images"
    layered_scenes_dir = PROJECT_ROOT / "input" / "scenes"
    output_dir = PROJECT_ROOT / "output"
    work_dir = PROJECT_ROOT / "work"
    generated_dir = work_dir / "generated-images"
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    print("[2/10] Validating script and visual sources")
    script = load_script(
        script_path, videos_dir, images_dir, scenes_dir=layered_scenes_dir
    )
    if dry_run:
        for scene in script.scenes:
            if scene.assets:
                load_layered_manifest(
                    layered_scenes_dir / scene.assets,
                    expected_width=config.video.width,
                    expected_height=config.video.height,
                )
        if script.visual.image_provider == "gemini_api" and not os.environ.get("GEMINI_API_KEY"):
            raise AutoEditorError(
                "BLOCKED_EXTERNAL: visual.image_provider=gemini_api cần GEMINI_API_KEY."
            )
        selected_motion_mode = motion_mode or script.visual.motion_mode
        if selected_motion_mode == "ai":
            if script.visual.motion_provider != "gemini_image_to_video":
                raise AutoEditorError(
                    "BLOCKED_EXTERNAL: motion_mode=ai cần visual.motion_provider="
                    "gemini_image_to_video."
                )
            if not os.environ.get("GEMINI_API_KEY"):
                raise AutoEditorError(
                    "BLOCKED_EXTERNAL: gemini_image_to_video cần GEMINI_API_KEY."
                )
        _display_dry_run(script, videos_dir, images_dir)
        return None

    print("[3/10] Resolving visual assets")
    assets = resolve_visual_assets(
        script, videos_dir, images_dir, generated_dir, layered_scenes_dir,
        force=force_images, provider=image_provider,
    )
    if generate_images_only:
        ready = sum(1 for asset in assets.values() if asset.kind in {"image", "layered"})
        print(f"GENERATE IMAGES COMPLETE - {ready} image/layered asset(s) ready.")
        return None

    require_executable(config.ffmpeg, "FFmpeg")
    require_executable(config.ffprobe, "ffprobe")
    if not config.kokoro_python.is_file():
        raise AutoEditorError(f"Không tìm thấy Kokoro Python: {config.kokoro_python}")
    audio_dir, scenes_dir, motion_dir, alignment_dir = _clean_work_directory(work_dir)

    print("[4/10] Generating narration")
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

    print("[5/10] Building audio master timeline")
    total = timeline[-1].end
    print(f"       Total narration timeline: {total:.2f} sec")

    print("[6/10] Forced word alignment")
    alignments = align_timeline(
        timeline, script.language, config.alignment, alignment_dir
    )
    for alignment in alignments:
        print(f"       Scene {alignment.scene_id:02d} ... {len(alignment.words)} words aligned")

    print("[7/10] Preparing visual scenes")
    selected_motion_mode = motion_mode or script.visual.motion_mode
    if selected_motion_mode == "ai":
        print(
            "       WARNING: AI image-to-video có thể thay đổi chi tiết ảnh; "
            "dùng local để preserve tốt nhất."
        )
    if selected_motion_mode == "ai" and ai_motion_provider is None:
        ai_motion_provider = create_ai_motion_provider(
            script.visual.motion_provider, script.visual.motion_model
        )
    prepared = _prepare_scenes(
        timeline, assets, scenes_dir, motion_dir, config, selected_motion_mode,
        ai_provider=ai_motion_provider,
        fallback_local=script.visual.ai_fallback_local,
    )
    joined_video = work_dir / "joined_video.mp4"
    transitions: list[SceneTransition] = []
    for scene in script.scenes[:-1]:
        asset = assets[scene.id]
        if asset.kind == "layered":
            transitions.append(load_layered_manifest(asset.path).transition_out)
        else:
            transitions.append(SceneTransition())
    if any(transition.type != "none" for transition in transitions):
        durations = [
            entry.duration + (config.audio.gap_ms / 1000.0 if index < len(timeline) - 1 else 0.0)
            for index, entry in enumerate(timeline)
        ]
        concat_video_scenes_with_transitions(
            prepared, durations, transitions, joined_video, config
        )
    else:
        concat_video_scenes(prepared, joined_video, config, work_dir)
    print("[8/10] Concatenating and normalizing narration")
    voice_path = output_dir / "voice.wav"
    concat_audio_scenes([entry.audio_path for entry in timeline], voice_path, config, work_dir)

    print("[9/10] Creating rolling word subtitles")
    cues = create_rolling_cues(alignments, timeline, config.subtitles)
    srt_path = output_dir / "subtitles.srt"
    ass_path = output_dir / "subtitles.ass"
    write_srt(cues, srt_path)
    write_ass(cues, ass_path, config.subtitles, config.video.width, config.video.height)

    final_path = reserve_final_video_path(output_dir)
    temporary = output_dir / f"{final_path.stem}.building.mp4"
    print(f"[10/10] Rendering {final_path.name}")
    try:
        if temporary.is_file():
            temporary.unlink()
        render_final_video(joined_video, voice_path, ass_path, temporary, config)
        atomic_replace_final(temporary, final_path)
    except BaseException:
        if temporary.is_file():
            temporary.unlink()
        if final_path.is_file() and final_path.stat().st_size == 0:
            final_path.unlink()
        raise
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
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--generate-images", action="store_true", help="Chỉ resolve/generate ảnh")
    actions.add_argument("--build", action="store_true", help="Build video (mặc định)")
    actions.add_argument("--run-all", action="store_true", help="Generate ảnh nếu cần rồi build")
    parser.add_argument("--force-images", action="store_true", help="Bỏ cache và tạo lại ảnh")
    parser.add_argument("--motion-mode", choices=("local", "ai", "auto"))
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    args = _parser().parse_args(argv)
    try:
        result = run_pipeline(
            args.script.resolve(), args.config.resolve(), args.dry_run,
            generate_images_only=args.generate_images,
            force_images=args.force_images,
            motion_mode=args.motion_mode,
        )
        if result:
            print("\nFINAL VIDEO:")
            print(result.resolve())
        return 0
    except AutoEditorError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nĐã hủy theo yêu cầu người dùng.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
