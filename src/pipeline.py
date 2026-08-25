from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from .alignment import (
    WhisperXAlignmentEngine, align_continuous_narration, align_pause_contexts,
    align_timeline,
)
from .config import AppConfig, load_config
from .ffmpeg_utils import probe_audio_duration, probe_duration, require_executable
from .image_assets import VisualAsset, resolve_visual_assets
from .layered_composer import render_layered_scene
from .layered_manifest import SceneTransition, load_layered_manifest
from .motion_service import render_image_motion
from .motion_providers.ai_image_to_video import create_ai_motion_provider
from .models import AutoEditorError, Script, TimelineEntry
from .script_loader import load_script
from .subtitles import (
    create_rolling_cues, create_subtitle_phrases, write_phrase_ass, write_srt,
    write_subtitle_diagnostics,
)
from .timing import build_timeline
from .transitions import (
    avoid_source_sfx_conflicts, build_transition_sfx_mix,
    schedule_pause_aware_transitions, write_transition_diagnostics,
)
from .tts_bridge import generate_narration
from .video_builder import (
    SourceAudioClip,
    build_source_audio_mix,
    concat_audio_scenes,
    concat_video_scenes,
    concat_video_scenes_with_transitions,
    prepare_video_scene,
    process_narration_audio,
    render_final_video,
    trim_narration_padding,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_FINAL_VIDEO_PATTERN = re.compile(r"FINAL_VIDEO_([0-9]+)\.mp4\Z")
LANGUAGE_FINAL_VIDEO_PATTERN = re.compile(r"FINAL_VIDEO_(EN|VI)_([0-9]+)\.mp4\Z")
FINAL_VIDEO_RESERVATION_ATTEMPTS = 100


def _language_tag(language: str) -> str:
    tag = language.upper()
    if tag not in {"EN", "VI"}:
        raise AutoEditorError("Output language hiện chỉ hỗ trợ EN hoặc VI.")
    return tag


def _existing_final_videos(
    output_dir: Path, language: str | None = None,
) -> list[tuple[int, Path]]:
    matches: list[tuple[int, Path]] = []
    tag = _language_tag(language) if language is not None else None
    for path in output_dir.iterdir():
        if not path.is_file():
            continue
        language_match = LANGUAGE_FINAL_VIDEO_PATTERN.fullmatch(path.name)
        if language_match and (tag is None or language_match.group(1) == tag):
            matches.append((int(language_match.group(2)), path))
            continue
        legacy_match = LEGACY_FINAL_VIDEO_PATTERN.fullmatch(path.name)
        if tag is None and legacy_match:
            matches.append((int(legacy_match.group(1)), path))
    return matches


def reserve_final_video_path(output_dir: Path, language: str | None = None) -> Path:
    """Atomically reserve the next max-plus-one final-video filename."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(FINAL_VIDEO_RESERVATION_ATTEMPTS):
        existing = _existing_final_videos(output_dir, language)
        next_number = max((number for number, _ in existing), default=0) + 1
        prefix = f"FINAL_VIDEO_{_language_tag(language)}" if language else "FINAL_VIDEO"
        candidate = output_dir / f"{prefix}_{next_number}.mp4"
        try:
            descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        os.close(descriptor)
        return candidate
    raise AutoEditorError(
        "Không thể giữ tên video final mới do có quá nhiều build đồng thời."
    )


def latest_final_video_path(output_dir: Path, language: str | None = None) -> Path:
    existing = _existing_final_videos(output_dir, language)
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
    for filename in (
        "tts_manifest.json", "video_concat.txt", "audio_concat.txt", "gap.wav",
        "joined_video.mp4", "source_sfx.wav", "transition_sfx.wav",
    ):
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
    visual_durations: tuple[float, ...] | None = None,
) -> list[Path]:
    results: list[Path] = []
    gap = config.audio.gap_ms / 1000.0
    for index, entry in enumerate(timeline):
        destination = scenes_dir / f"scene_{entry.scene.id:03d}.mp4"
        target_duration = (
            visual_durations[index]
            if visual_durations is not None
            else entry.duration + (gap if index < len(timeline) - 1 else 0.0)
        )
        asset = assets[entry.scene.id]
        print(f"       Scene {entry.scene.id:02d} {asset.kind} -> {target_duration:.2f} sec")
        if asset.kind == "video":
            prepare_video_scene(
                asset.path, destination, target_duration, config,
                source_duration=probe_duration(asset.path, config.ffprobe),
            )
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


def quantize_visual_durations(
    timeline: tuple[TimelineEntry, ...], fps: int,
) -> tuple[float, ...]:
    """Quantize cumulative cuts, avoiding per-scene rounding drift.

    Intermediate boundaries use nearest-frame timing. The final boundary uses
    ceil so the visual master can never truncate the audio master.
    """
    if not timeline or fps <= 0:
        raise AutoEditorError("Timeline/FPS không hợp lệ khi lượng tử hóa scene.")
    frame_boundaries = [0]
    for index, entry in enumerate(timeline):
        raw = entry.end * fps
        frame = math.ceil(raw - 1e-9) if index == len(timeline) - 1 else round(raw)
        if frame <= frame_boundaries[-1]:
            frame = frame_boundaries[-1] + 1
        frame_boundaries.append(frame)
    return tuple(
        (right - left) / fps
        for left, right in zip(frame_boundaries, frame_boundaries[1:])
    )


def write_freeze_diagnostics(
    timeline: tuple[TimelineEntry, ...], visual_durations: tuple[float, ...],
    assets: dict[int, VisualAsset], config: AppConfig, path: Path,
) -> dict[str, object]:
    scenes: list[dict[str, object]] = []
    for entry, target in zip(timeline, visual_durations):
        asset = assets[entry.scene.id]
        source_duration = (
            probe_duration(asset.path, config.ffprobe) if asset.kind == "video" else target
        )
        freeze = max(0.0, target - source_duration)
        masks_tail = freeze > config.transitions.freeze_tail_motion_start_ms / 1000.0
        if freeze <= 0.25:
            severity = "none"
            recommendation = "no_concern"
        elif freeze <= 0.5:
            severity = "subtle"
            recommendation = "tiny_continuing_push"
        elif freeze <= 0.9:
            severity = "noticeable"
            recommendation = "stronger_slow_push"
        else:
            severity = "poor_source_coverage"
            recommendation = "masked_but_report_insufficient_coverage"
        scenes.append({
            "scene_id": entry.scene.id, "asset_kind": asset.kind,
            "source_duration": round(source_duration, 6),
            "target_duration": round(target, 6),
            "freeze_duration": round(freeze, 6),
            "tail_motion_masked": masks_tail,
            "tail_motion": "deterministic_subtle_zoom_pan" if masks_tail else "none",
            "insufficient_coverage": freeze > 0.9,
            "severity": severity,
            "recommendation": recommendation,
        })
    freezes = [float(scene["freeze_duration"]) for scene in scenes]
    payload: dict[str, object] = {
        "scene_count": len(scenes),
        "maximum_freeze": round(max(freezes), 6) if freezes else 0.0,
        "over_750ms": sum(value > 0.75 for value in freezes),
        "over_900ms": sum(value > 0.9 for value in freezes),
        "over_1500ms": sum(value > 1.5 for value in freezes),
        "over_2000ms": sum(value > 2.0 for value in freezes),
        "scenes": scenes,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _collect_source_audio_clips(
    timeline: tuple[TimelineEntry, ...], assets: dict[int, VisualAsset],
    config: AppConfig,
) -> list[SourceAudioClip]:
    clips: list[SourceAudioClip] = []
    if not config.audio.preserve_source_audio:
        return clips
    for index, entry in enumerate(timeline):
        asset = assets[entry.scene.id]
        if asset.kind != "video":
            continue
        source_duration = probe_audio_duration(asset.path, config.ffprobe)
        if source_duration is None:
            continue
        visual_duration = entry.duration + (
            config.audio.gap_ms / 1000.0 if index < len(timeline) - 1 else 0.0
        )
        clips.append(
            SourceAudioClip(asset.path, entry.start, min(source_duration, visual_duration))
        )
    return clips


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
    narration_chunks = generate_narration(
        script, config.kokoro_python, PROJECT_ROOT / "src" / "kokoro_worker.py",
        audio_dir, work_dir, config.audio.sample_rate,
        config.audio.narration_mode, config.audio.continuous_chunk_scenes,
    )
    narration_paths = [chunk.output_path for chunk in narration_chunks]
    # Continuous chunks get a clean edge; an explicit language-specific gap is
    # inserted at concat time. This avoids both hard joins and accidental
    # stacking of retained TTS padding plus the configured join cadence.
    trim_narration_padding(
        narration_paths, config,
        edge_silence_ms=0 if config.audio.narration_mode == "continuous" else None,
    )
    alignment_engine = WhisperXAlignmentEngine(script.language, config.alignment)
    pause_contexts = align_pause_contexts(
        tuple(
            (chunk.output_path, chunk.text, probe_duration(chunk.output_path, config.ffprobe))
            for chunk in narration_chunks
        ),
        script.language, config.alignment,
        work_dir / "diagnostics" / "pause_context_alignment", alignment_engine,
    )
    compression_reports = process_narration_audio(
        narration_paths, config, work_dir / "diagnostics" / "pause_compression.json",
        language=script.language, aligned_words=pause_contexts,
    )
    print(
        f"       Mode: {config.audio.narration_mode} | "
        f"{len(narration_chunks)} TTS chunk(s) | "
        f"{sum(item.removed_duration for item in compression_reports):.3f}s removed"
    )

    print("[5/10] Building audio master timeline")
    voice_path = output_dir / "voice.wav"
    join_gap_ms = (
        config.audio.pause_profiles[script.language].chunk_join_ms
        if config.audio.narration_mode == "continuous" else config.audio.gap_ms
    )
    chunk_durations = tuple(
        probe_duration(path, config.ffprobe) for path in narration_paths
    )
    alignment_segments: list[dict[str, object]] = []
    segment_cursor = 0.0
    for index, (chunk, duration) in enumerate(zip(narration_chunks, chunk_durations)):
        alignment_segments.append({
            "text": chunk.text, "start": segment_cursor,
            "end": segment_cursor + duration,
        })
        segment_cursor += duration
        if index < len(narration_chunks) - 1:
            segment_cursor += join_gap_ms / 1000.0
    concat_audio_scenes(
        narration_paths, voice_path, config, work_dir, gap_ms=join_gap_ms
    )
    voice_duration = probe_duration(voice_path, config.ffprobe)
    if config.audio.narration_mode == "continuous":
        timeline: tuple[TimelineEntry, ...] = ()
    else:
        timeline = build_timeline(
            script.scenes, audio_dir,
            lambda path: probe_duration(path, config.ffprobe), config.audio.gap_ms,
        )
    for entry in timeline:
        print(f"       Scene {entry.scene.id:02d} ... {entry.duration:.2f} sec")
    print(f"       Total narration master: {voice_duration:.2f} sec")

    print("[6/10] Forced word alignment")
    if config.audio.narration_mode == "continuous":
        timeline, alignments = align_continuous_narration(
            script.scenes, voice_path, voice_duration, script.language,
            config.alignment, alignment_dir, engine=alignment_engine,
            transcript_segments=tuple(alignment_segments),
        )
        for entry in timeline:
            print(f"       Scene {entry.scene.id:02d} ... {entry.duration:.2f} sec")
    else:
        alignments = align_timeline(
            timeline, script.language, config.alignment, alignment_dir,
            engine=alignment_engine,
        )
    total = timeline[-1].end
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
    visual_durations = quantize_visual_durations(timeline, config.video.fps)
    write_freeze_diagnostics(
        timeline, visual_durations, assets, config,
        work_dir / "diagnostics" / "visual_freeze.json",
    )
    transition_decisions = schedule_pause_aware_transitions(
        timeline, alignments, config.transitions, fps=config.video.fps
    )
    prepared = _prepare_scenes(
        timeline, assets, scenes_dir, motion_dir, config, selected_motion_mode,
        ai_provider=ai_motion_provider,
        fallback_local=script.visual.ai_fallback_local,
        visual_durations=visual_durations,
    )
    joined_video = work_dir / "joined_video.mp4"
    transitions: list[SceneTransition] = []
    for index, scene in enumerate(script.scenes[:-1]):
        decision = transition_decisions[index]
        if config.transitions.pause_aware:
            transitions.append(
                SceneTransition(
                    decision.effect, decision.visual_duration, decision.settle_duration
                )
                if decision.has_visual else SceneTransition()
            )
        else:
            asset = assets[scene.id]
            transitions.append(
                load_layered_manifest(asset.path).transition_out
                if asset.kind == "layered" else SceneTransition()
            )
    if any(transition.type != "none" for transition in transitions):
        concat_video_scenes_with_transitions(
            prepared, visual_durations, transitions, joined_video, config
        )
    else:
        concat_video_scenes(prepared, joined_video, config, work_dir)
    print("[8/10] Mixing source-video SFX")
    source_audio_clips = _collect_source_audio_clips(timeline, assets, config)
    source_sfx_path = work_dir / "source_sfx.wav"
    has_source_sfx = build_source_audio_mix(
        source_audio_clips, source_sfx_path, total, config
    )
    print(f"       Source-video audio: {len(source_audio_clips)} scene(s) mixed")
    transition_decisions = avoid_source_sfx_conflicts(
        transition_decisions, source_sfx_path if has_source_sfx else None,
        config.transitions,
    )
    transition_sfx_path = work_dir / "transition_sfx.wav"
    has_transition_sfx = build_transition_sfx_mix(
        transition_decisions, transition_sfx_path, total, config
    )
    transition_report = write_transition_diagnostics(
        transition_decisions, timeline, alignments,
        work_dir / "diagnostics" / "transitions.json",
    )
    print(
        "       Pause-aware: "
        f"{transition_report['eligible_pause_count']} eligible | "
        f"{transition_report['visual_effect_count']} visual | "
        f"{transition_report['transition_sfx_count']} transition SFX"
    )

    print("[9/10] Creating stable phrase subtitles")
    phrases = create_subtitle_phrases(alignments, timeline, config.subtitles)
    cues = create_rolling_cues(alignments, timeline, config.subtitles)
    srt_path = output_dir / "subtitles.srt"
    ass_path = output_dir / "subtitles.ass"
    write_srt(cues, srt_path)
    write_phrase_ass(
        phrases, ass_path, config.subtitles, config.video.width, config.video.height
    )
    write_subtitle_diagnostics(
        phrases, work_dir / "diagnostics" / "subtitles.json", config.subtitles
    )

    final_path = reserve_final_video_path(output_dir, script.language)
    temporary = output_dir / f"{final_path.stem}.building.mp4"
    print(f"[10/10] Rendering {final_path.name}")
    try:
        if temporary.is_file():
            temporary.unlink()
        render_final_video(
            joined_video, voice_path, ass_path, temporary, config,
            source_sfx_path if has_source_sfx else None,
            transition_sfx_path if has_transition_sfx else None,
        )
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
