from __future__ import annotations

import json
import math
import sys
import wave
from array import array
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

from .config import AppConfig, TransitionConfig
from .ffmpeg_utils import probe_audio_duration, run_media_command
from .models import AutoEditorError, SceneAlignment, TimelineEntry, WordTiming
from .visual_quality import SceneVisualProfile


PAPER_PRESETS = ("paper_swipe", "collage_push", "paper_wipe")
MICRO_PRESETS = ("micro_crossfade", "micro_push")
SFX_PREFIXES = {
    "paper_swipe": ("paper_swipe", "paper_rustle", "page_turn"),
    "paper_slide": ("paper_swipe", "soft_whoosh", "paper_rustle"),
    "paper_wipe": ("paper_swipe", "page_turn", "paper_rustle"),
    "collage_push": ("soft_whoosh", "paper_swipe"),
}


@dataclass(frozen=True)
class PauseTransition:
    boundary_index: int
    from_scene: int
    to_scene: int
    boundary_time: float
    pause_start: float
    pause_end: float
    pause_seconds: float
    pause_class: str
    eligible: bool
    effect: str
    bridge_start: float | None
    visual_start: float | None
    visual_end: float | None
    visual_duration: float
    pre_roll_duration: float
    settle_duration: float
    sfx_path: Path | None
    sfx_start: float | None
    visual_intent: str = "pause_only"
    source_rms_db: float | None = None
    reason: str = ""

    @property
    def has_visual(self) -> bool:
        return self.effect != "none" and self.visual_duration > 0

    @property
    def has_sfx(self) -> bool:
        return self.sfx_path is not None and self.sfx_start is not None


@dataclass(frozen=True)
class TransitionSfxClip:
    path: Path
    start: float
    duration: float


def _global_words(
    alignment: SceneAlignment, entry: TimelineEntry,
) -> tuple[WordTiming, ...]:
    return tuple(
        WordTiming(word.word, entry.start + word.start, entry.start + word.end)
        for word in alignment.words
    )


def _pause_class(seconds: float, *, boundary: bool) -> str:
    if seconds > 0.7:
        return "long_abnormal_dead_air"
    if boundary:
        if seconds < 0.18:
            return "short_cut"
        if seconds < 0.25:
            return "micro_bridge"
        if seconds < 0.38:
            return "documentary_bridge"
        if seconds < 0.50:
            return "full_bridge"
        return "long_bridge"
    if seconds >= 0.3:
        return "sentence_ending"
    return "internal_phrase"


def discover_transition_sfx(directory: Path) -> tuple[Path, ...]:
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(
            (
                path for path in directory.iterdir()
                if path.is_file() and path.suffix.casefold() in {".wav", ".mp3", ".m4a"}
            ),
            key=lambda path: path.name.casefold(),
        )
    )


def _select_sfx(effect: str, boundary_index: int, assets: Sequence[Path]) -> Path | None:
    prefixes = SFX_PREFIXES.get(effect, ())
    candidates = tuple(
        asset for prefix in prefixes
        for asset in assets
        if asset.stem.casefold().startswith(prefix)
    )
    if not candidates:
        return None
    unique = tuple(dict.fromkeys(candidates))
    return unique[(boundary_index * 7 + 3) % len(unique)]


def _should_select(boundary_index: int, pause_ms: float, config: TransitionConfig) -> bool:
    if pause_ms > 700:
        return True
    if pause_ms >= config.strong_trigger_ms:
        return boundary_index == 1 or boundary_index % 2 == 0 or boundary_index % 7 == 0
    if pause_ms >= config.preferred_trigger_ms:
        return boundary_index % 2 == 0
    return boundary_index % 5 == 0


def _adapt_transition_ms(pause_ms: float, config: TransitionConfig) -> int:
    if pause_ms < config.minimum_pause_ms:
        return min(
            config.micro_transition_max_ms,
            max(config.micro_transition_min_ms, round(pause_ms * config.transition_ratio)),
        )
    if pause_ms < 380:
        return min(
            300,
            max(config.minimum_transition_ms, round(pause_ms * config.transition_ratio)),
        )
    if pause_ms < 500:
        return min(
            340,
            max(280, round(pause_ms * config.transition_ratio)),
        )
    return min(config.max_transition_ms, 340)


def _effect_for_boundary(
    boundary_index: int, pause_ms: float, config: TransitionConfig,
    left_profile: SceneVisualProfile | None = None,
    right_profile: SceneVisualProfile | None = None,
) -> tuple[str, bool, str]:
    """Choose a sparse transition from pause, energy, and visual density."""
    left_dense = left_profile is not None and left_profile.density_class == "high"
    right_dense = right_profile is not None and right_profile.density_class == "high"
    left_low = left_profile is not None and left_profile.motion_class == "low"
    right_low = right_profile is not None and right_profile.motion_class == "low"
    left_freeze = left_profile is not None and left_profile.coverage_shortfall >= 0.25

    if pause_ms < config.minimum_pause_ms:
        if pause_ms >= config.micro_pause_ms and left_freeze:
            return "micro_crossfade", False, "freeze_tail_exit_soften"
        return "none", False, "preserve_short_cut"

    if pause_ms < config.preferred_trigger_ms:
        if left_low or right_low:
            return "micro_crossfade", False, "low_motion_short_pause_soften"
        return "micro_crossfade", False, "short_pause_continuity"
    if left_dense and right_dense:
        return "micro_crossfade", False, "dense_to_dense_reduce_competition"
    if left_dense != right_dense:
        if _should_select(boundary_index, pause_ms, config):
            return "paper_wipe", True, "density_change_reveal"
        return "micro_crossfade", False, "density_change_soften"
    if left_low and right_low and pause_ms >= config.strong_trigger_ms:
        return "collage_push", True, "low_motion_directional_bridge"
    noticeable = _should_select(boundary_index, pause_ms, config)
    if noticeable:
        return (
            PAPER_PRESETS[(boundary_index * 5 + 1) % len(PAPER_PRESETS)],
            True,
            "pause_energy_paper_accent",
        )
    return "micro_crossfade", False, "continuity_micro_crossfade"


def schedule_pause_aware_transitions(
    timeline: Sequence[TimelineEntry], alignments: Sequence[SceneAlignment],
    config: TransitionConfig, *, fps: int = 30,
    visual_profiles: dict[int, SceneVisualProfile] | None = None,
) -> tuple[PauseTransition, ...]:
    """Schedule deterministic bridges wholly inside existing narration pauses.

    The main transition begins after a short pre-roll and ends before a one- or
    two-frame settle. This function never changes a TimelineEntry and therefore
    cannot delay narration.
    """
    if fps <= 0:
        raise AutoEditorError("FPS transition phải > 0.")
    if len(timeline) < 2:
        return ()
    by_scene = {alignment.scene_id: alignment for alignment in alignments}
    assets = discover_transition_sfx(config.sfx_dir) if config.enable_sfx else ()
    decisions: list[PauseTransition] = []
    for boundary_index, (left, right) in enumerate(zip(timeline, timeline[1:]), 1):
        left_alignment = by_scene.get(left.scene.id)
        right_alignment = by_scene.get(right.scene.id)
        if not left_alignment or not left_alignment.words:
            raise AutoEditorError(
                f"Thiếu word alignment cho transition scene {left.scene.id:02d}."
            )
        if not right_alignment or not right_alignment.words:
            raise AutoEditorError(
                f"Thiếu word alignment cho transition scene {right.scene.id:02d}."
            )
        previous_end = _global_words(left_alignment, left)[-1].end
        next_start = _global_words(right_alignment, right)[0].start
        pause = max(0.0, next_start - previous_end)
        pause_ms = pause * 1000.0
        eligible = config.pause_aware and pause_ms >= config.minimum_pause_ms
        left_profile = (visual_profiles or {}).get(left.scene.id)
        right_profile = (visual_profiles or {}).get(right.scene.id)
        selected_effect, accented, visual_intent = _effect_for_boundary(
            boundary_index, pause_ms, config, left_profile, right_profile
        )
        bridge = bool(
            config.pause_aware and config.enable_visual
            and selected_effect != "none"
        )
        if not config.pause_aware:
            reason = "pause_aware_disabled"
        elif selected_effect == "none":
            reason = visual_intent
        elif not config.enable_visual:
            reason = "visual_disabled"
        elif pause_ms < config.minimum_pause_ms:
            reason = "micro_bridge"
        else:
            reason = "continuity_bridge"
        effect = selected_effect if bridge else "none"
        accented = accented if bridge else False
        duration = 0.0
        bridge_start: float | None = None
        visual_start: float | None = None
        visual_end: float | None = None
        pre_roll_duration = 0.0
        settle_duration = 0.0
        if bridge:
            pause_start_frame = math.ceil(previous_end * fps - 1e-9)
            boundary_frame = round(next_start * fps)
            available_frames = boundary_frame - pause_start_frame
            if available_frames < 3:
                bridge = False
                effect = "none"
                accented = False
                reason = "insufficient_frame_window"
            else:
                settle_frames = max(1, round(config.settle_ms * fps / 1000.0))
                settle_frames = min(settle_frames, max(1, available_frames // 4))
                pre_roll_frames = (
                    0 if pause_ms < config.minimum_pause_ms
                    else max(1, math.floor(available_frames * config.pre_roll_ratio))
                )
                requested_raw = _adapt_transition_ms(pause_ms, config) * fps / 1000.0
                requested_frames = max(
                    1,
                    round(requested_raw)
                    if pause_ms < config.minimum_pause_ms
                    else math.ceil(requested_raw - 1e-9),
                )
                requested_frames = min(
                    requested_frames,
                    max(1, math.floor(config.max_transition_ms * fps / 1000.0)),
                )
                maximum_transition_frames = available_frames - pre_roll_frames - settle_frames
                if maximum_transition_frames < 1:
                    pre_roll_frames = 0
                    maximum_transition_frames = available_frames - pre_roll_frames - settle_frames
                duration_frames = min(requested_frames, maximum_transition_frames)
                transition_end_frame = boundary_frame - settle_frames
                transition_start_frame = transition_end_frame - duration_frames
                bridge_start = pause_start_frame / fps
                visual_start = transition_start_frame / fps
                visual_end = transition_end_frame / fps
                duration = duration_frames / fps
                pre_roll_duration = (transition_start_frame - pause_start_frame) / fps
                settle_duration = settle_frames / fps
            if bridge and visual_start is not None and visual_start < previous_end - 1e-6:
                raise AutoEditorError("Transition vượt ra ngoài narration pause hiện có.")
        sfx_path = (
            _select_sfx(effect, boundary_index, assets) if bridge and accented else None
        )
        sfx_start = visual_start if sfx_path is not None else None
        if bridge and accented and config.enable_sfx and sfx_path is None:
            reason = "scheduled_visual_missing_sfx"
        decisions.append(PauseTransition(
            boundary_index=boundary_index,
            from_scene=left.scene.id,
            to_scene=right.scene.id,
            boundary_time=next_start,
            pause_start=previous_end,
            pause_end=next_start,
            pause_seconds=pause,
            pause_class=_pause_class(pause, boundary=True),
            eligible=eligible,
            effect=effect,
            bridge_start=bridge_start,
            visual_start=visual_start,
            visual_end=visual_end,
            visual_duration=duration,
            pre_roll_duration=pre_roll_duration,
            settle_duration=settle_duration,
            sfx_path=sfx_path,
            sfx_start=sfx_start,
            visual_intent=visual_intent,
            reason=reason,
        ))
    return tuple(decisions)


def measure_wav_window_rms_db(path: Path, start: float, duration: float) -> float:
    if duration <= 0:
        return -math.inf
    try:
        with wave.open(str(path), "rb") as source:
            if source.getsampwidth() != 2:
                raise AutoEditorError("Source SFX master phải là PCM 16-bit để đo conflict.")
            sample_rate = source.getframerate()
            frame_start = min(source.getnframes(), max(0, round(start * sample_rate)))
            source.setpos(frame_start)
            payload = source.readframes(round(duration * sample_rate))
    except (OSError, wave.Error) as exc:
        raise AutoEditorError(f"Không đo được source SFX conflict: {exc}") from exc
    samples = array("h")
    samples.frombytes(payload)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return -math.inf
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
    return -math.inf if rms <= 0 else 20.0 * math.log10(rms / 32767.0)


def avoid_source_sfx_conflicts(
    decisions: Sequence[PauseTransition], source_sfx_path: Path | None,
    config: TransitionConfig,
) -> tuple[PauseTransition, ...]:
    if source_sfx_path is None or not source_sfx_path.is_file():
        return tuple(decisions)
    checked: list[PauseTransition] = []
    for decision in decisions:
        if not decision.has_sfx:
            checked.append(decision)
            continue
        rms_db = measure_wav_window_rms_db(
            source_sfx_path, decision.sfx_start or 0.0, decision.visual_duration
        )
        if rms_db >= config.source_conflict_threshold_db:
            checked.append(replace(
                decision, sfx_path=None, sfx_start=None, source_rms_db=rms_db,
                reason="visual_only_source_sfx_conflict",
            ))
        else:
            checked.append(replace(decision, source_rms_db=rms_db))
    return tuple(checked)


def build_transition_sfx_mix(
    decisions: Sequence[PauseTransition], destination: Path,
    total_duration: float, config: AppConfig,
) -> bool:
    clips: list[TransitionSfxClip] = []
    for decision in decisions:
        if not decision.has_sfx:
            continue
        asset_duration = probe_audio_duration(decision.sfx_path, config.ffprobe)
        if asset_duration is None:
            continue
        clips.append(TransitionSfxClip(
            decision.sfx_path,
            decision.sfx_start or 0.0,
            min(asset_duration, decision.visual_duration),
        ))
    if not config.transitions.enable_sfx or not clips:
        return False
    command = [config.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for clip in clips:
        command.extend(["-i", str(clip.path)])
    filters: list[str] = []
    labels: list[str] = []
    for index, clip in enumerate(clips):
        fade = min(config.transitions.sfx_fade_ms / 1000.0, clip.duration / 2.0)
        fade_out_start = max(0.0, clip.duration - fade)
        delay_ms = round(clip.start * 1000.0)
        label = f"transition{index}"
        labels.append(f"[{label}]")
        chain = (
            f"[{index}:a:0]atrim=start=0:duration={clip.duration:.6f},"
            "asetpts=PTS-STARTPTS,"
            f"aresample={config.audio.mix_sample_rate},"
            f"aformat=sample_fmts=fltp:sample_rates={config.audio.mix_sample_rate}:"
            "channel_layouts=stereo,"
            f"volume={config.transitions.sfx_gain_db:.3f}dB"
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
            "duration=longest:dropout_transition=0:normalize=0[transitionbase]"
        )
        base = "[transitionbase]"
    filters.append(
        f"{base}apad=whole_dur={total_duration:.6f},"
        f"atrim=duration={total_duration:.6f}[transitions]"
    )
    command.extend([
        "-filter_complex", ";".join(filters), "-map", "[transitions]",
        "-ar", str(config.audio.mix_sample_rate), "-ac", "2",
        "-c:a", "pcm_s16le", str(destination),
    ])
    run_media_command(command, "tạo transition SFX master")
    return True


def _internal_pause_summary(
    timeline: Sequence[TimelineEntry], alignments: Sequence[SceneAlignment],
) -> dict[str, object]:
    by_scene = {alignment.scene_id: alignment for alignment in alignments}
    records: list[dict[str, object]] = []
    for entry in timeline:
        alignment = by_scene[entry.scene.id]
        words = _global_words(alignment, entry)
        for left, right in zip(words, words[1:]):
            pause = max(0.0, right.start - left.end)
            if pause >= 0.15:
                records.append({
                    "scene_id": entry.scene.id,
                    "start": round(left.end, 6),
                    "end": round(right.start, 6),
                    "pause_ms": round(pause * 1000),
                    "class": _pause_class(pause, boundary=False),
                    "effect": "none",
                    "reason": "internal_pause_no_major_transition",
                })
    return {
        "count_at_least_150ms": len(records),
        "long_abnormal_count": sum(
            record["class"] == "long_abnormal_dead_air" for record in records
        ),
        "records": records,
    }


def write_transition_diagnostics(
    decisions: Sequence[PauseTransition], timeline: Sequence[TimelineEntry],
    alignments: Sequence[SceneAlignment], path: Path,
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for decision in decisions:
        records.append({
            "boundary_index": decision.boundary_index,
            "from_scene": decision.from_scene,
            "to_scene": decision.to_scene,
            "boundary_time": round(decision.boundary_time, 6),
            "pause_start": round(decision.pause_start, 6),
            "pause_end": round(decision.pause_end, 6),
            "pause_ms": round(decision.pause_seconds * 1000),
            "class": decision.pause_class,
            "eligible": decision.eligible,
            "effect": decision.effect,
            "visual_intent": decision.visual_intent,
            "bridge_start": (
                round(decision.bridge_start, 6)
                if decision.bridge_start is not None else None
            ),
            "visual_start": (
                round(decision.visual_start, 6)
                if decision.visual_start is not None else None
            ),
            "visual_end": (
                round(decision.visual_end, 6)
                if decision.visual_end is not None else None
            ),
            "visual_duration_ms": round(decision.visual_duration * 1000),
            "pre_roll_ms": round(decision.pre_roll_duration * 1000),
            "settle_ms": round(decision.settle_duration * 1000),
            "sfx": decision.sfx_path.name if decision.sfx_path else None,
            "sfx_start": round(decision.sfx_start, 6) if decision.sfx_start else None,
            "source_rms_db": (
                round(decision.source_rms_db, 3)
                if decision.source_rms_db is not None and math.isfinite(decision.source_rms_db)
                else None
            ),
            "reason": decision.reason,
        })
    visual_count = sum(decision.has_visual for decision in decisions)
    sfx_count = sum(decision.has_sfx for decision in decisions)
    payload: dict[str, object] = {
        "boundary_count": len(decisions),
        "eligible_pause_count": sum(decision.eligible for decision in decisions),
        "visual_effect_count": visual_count,
        "transition_sfx_count": sfx_count,
        "both_count": sum(
            decision.has_visual and decision.has_sfx for decision in decisions
        ),
        "intentionally_untouched_count": sum(
            not decision.has_visual for decision in decisions
        ),
        "narration_timeline_changed": False,
        "boundaries": records,
        "internal_pauses": _internal_pause_summary(timeline, alignments),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
