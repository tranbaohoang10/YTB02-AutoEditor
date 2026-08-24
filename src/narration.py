from __future__ import annotations

import math
import os
import sys
import wave
from array import array
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from .models import AutoEditorError


@dataclass(frozen=True)
class PauseRegion:
    start_frame: int
    end_frame: int
    sample_rate: int

    @property
    def duration_ms(self) -> float:
        return (self.end_frame - self.start_frame) * 1000.0 / self.sample_rate


@dataclass(frozen=True)
class PauseCompressionEdit:
    start_seconds: float
    original_ms: float
    target_ms: float
    removed_ms: float
    context: str
    preceding_word: str | None


@dataclass(frozen=True)
class PauseCompressionReport:
    path: str
    original_duration: float
    compressed_duration: float
    removed_duration: float
    detected_pause_count: int
    compressed_pause_count: int
    edits: tuple[PauseCompressionEdit, ...]

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["edits"] = [asdict(edit) for edit in self.edits]
        return result


def read_pcm16_mono(path: Path) -> tuple[wave._wave_params, array]:
    try:
        with wave.open(str(path), "rb") as source:
            parameters = source.getparams()
            frames = source.readframes(source.getnframes())
    except (OSError, wave.Error) as exc:
        raise AutoEditorError(f"Không đọc được narration WAV {path}: {exc}") from exc
    if parameters.nchannels != 1 or parameters.sampwidth != 2:
        raise AutoEditorError(f"Narration WAV phải là mono PCM 16-bit: {path.name}")
    samples = array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    return parameters, samples


def write_pcm16_mono(path: Path, parameters: wave._wave_params, samples: array) -> None:
    frames = array("h", samples)
    if sys.byteorder != "little":
        frames.byteswap()
    temporary = path.with_suffix(".pause-compressed.wav")
    try:
        with wave.open(str(temporary), "wb") as output:
            output.setparams(parameters)
            output.writeframes(frames.tobytes())
        os.replace(temporary, path)
    finally:
        if temporary.is_file():
            temporary.unlink()


def detect_pause_regions(
    samples: Sequence[int], sample_rate: int, threshold_db: float,
    minimum_ms: int, *, window_ms: int = 10,
) -> tuple[PauseRegion, ...]:
    """Detect near-silence with RMS plus a peak guard for quiet phonemes."""
    if sample_rate <= 0 or minimum_ms < 0 or window_ms <= 0:
        raise AutoEditorError("Thông số phát hiện khoảng nghỉ không hợp lệ.")
    window = max(1, round(sample_rate * window_ms / 1000.0))
    minimum = max(1, round(sample_rate * minimum_ms / 1000.0))
    threshold = 32767.0 * 10 ** (threshold_db / 20.0)
    silent_windows: list[tuple[int, int]] = []
    for start in range(0, len(samples), window):
        end = min(len(samples), start + window)
        chunk = samples[start:end]
        if not chunk:
            continue
        square_sum = sum(sample * sample for sample in chunk)
        rms = math.sqrt(square_sum / len(chunk))
        peak = max(abs(sample) for sample in chunk)
        # The peak guard deliberately prefers a false negative over clipping a
        # low-energy consonant whose RMS alone happens to sit below threshold.
        if rms <= threshold and peak <= threshold:
            silent_windows.append((start, end))

    regions: list[PauseRegion] = []
    if not silent_windows:
        return ()
    region_start, region_end = silent_windows[0]
    for start, end in silent_windows[1:]:
        if start == region_end:
            region_end = end
            continue
        if region_end - region_start >= minimum:
            regions.append(PauseRegion(region_start, region_end, sample_rate))
        region_start, region_end = start, end
    if region_end - region_start >= minimum:
        regions.append(PauseRegion(region_start, region_end, sample_rate))
    return tuple(regions)


def pause_context(preceding_word: str | None) -> str:
    token = (preceding_word or "").rstrip()
    if token.endswith((".", "!", "?", "…")):
        return "sentence"
    if token.endswith((";", ":", "—", "–")):
        return "clause"
    if token.endswith(","):
        return "comma"
    return "neutral"


def pause_target_ms(
    duration_ms: float, audio_config: Any, language: str = "en",
    preceding_word: str | None = None,
) -> float:
    if duration_ms <= audio_config.pause_short_max_ms:
        return duration_ms
    profile = audio_config.pause_profiles[language]
    context = pause_context(preceding_word)
    contextual = {
        "comma": profile.comma_target_ms,
        "clause": profile.clause_target_ms,
        "sentence": profile.sentence_target_ms,
    }.get(context)
    if contextual is not None:
        return min(duration_ms, float(contextual))
    if duration_ms <= audio_config.pause_medium_max_ms:
        return min(duration_ms, float(profile.neutral_medium_target_ms))
    if duration_ms <= audio_config.pause_long_max_ms:
        return min(duration_ms, float(profile.neutral_long_target_ms))
    return min(duration_ms, float(profile.neutral_very_long_target_ms))


def _crossfade(left: Sequence[int], right: Sequence[int]) -> array:
    if len(left) != len(right):
        raise AutoEditorError("Hai phía crossfade narration không cùng độ dài.")
    mixed = array("h")
    count = len(left)
    if count == 0:
        return mixed
    for index, (left_sample, right_sample) in enumerate(zip(left, right)):
        ratio = (index + 1) / (count + 1)
        value = round(left_sample * (1.0 - ratio) + right_sample * ratio)
        mixed.append(max(-32768, min(32767, value)))
    return mixed


def _preceding_word(
    region: PauseRegion, words: Sequence[Any], sample_rate: int,
) -> str | None:
    pause_start = region.start_frame / sample_rate
    candidates = [word for word in words if float(word.end) <= pause_start + 0.04]
    return str(candidates[-1].word) if candidates else None


def compress_smart_pauses(
    path: Path, audio_config: Any, language: str = "en",
    aligned_words: Sequence[Any] = (),
) -> PauseCompressionReport:
    """Shorten only detected internal near-silence; never time-compress speech."""
    parameters, samples = read_pcm16_mono(path)
    sample_rate = parameters.framerate
    original_duration = len(samples) / sample_rate
    regions = detect_pause_regions(
        samples, sample_rate, audio_config.pause_threshold_db,
        audio_config.pause_min_detect_ms,
    )
    guard = round(sample_rate * audio_config.pause_edge_guard_ms / 1000.0)
    crossfade = round(sample_rate * audio_config.pause_crossfade_ms / 1000.0)
    if language not in audio_config.pause_profiles:
        raise AutoEditorError(f"Không có pause profile cho ngôn ngữ {language!r}.")
    selected: list[tuple[PauseRegion, int, int, str, str | None]] = []
    for region in regions:
        # Outer padding is handled separately. Never turn a file edge into a
        # hard join and never touch pauses that the configured policy keeps.
        if region.start_frame == 0 or region.end_frame == len(samples):
            continue
        preceding = _preceding_word(region, aligned_words, sample_rate)
        context = pause_context(preceding)
        target_ms = pause_target_ms(region.duration_ms, audio_config, language, preceding)
        target = round(sample_rate * target_ms / 1000.0)
        if target >= region.end_frame - region.start_frame:
            continue
        if target < 2 * (guard + crossfade):
            raise AutoEditorError(
                "Pause target quá ngắn so với edge guard/crossfade; hãy tăng target."
            )
        selected.append((region, target, crossfade, context, preceding))

    output = array("h")
    edits: list[PauseCompressionEdit] = []
    cursor = 0
    for region, target, fade, context, preceding in selected:
        left_keep = target // 2
        right_keep = target - left_keep
        left_mix_start = region.start_frame + left_keep - fade
        left_mix_end = region.start_frame + left_keep
        right_mix_start = region.end_frame - right_keep - fade
        right_mix_end = region.end_frame - right_keep
        if left_mix_start < cursor or right_mix_start < left_mix_end:
            raise AutoEditorError("Khoảng nghỉ narration chồng lấn khi nén.")
        output.extend(samples[cursor:left_mix_start])
        output.extend(
            _crossfade(
                samples[left_mix_start:left_mix_end],
                samples[right_mix_start:right_mix_end],
            )
        )
        cursor = region.end_frame - right_keep
        actual_target_ms = target * 1000.0 / sample_rate
        edits.append(
            PauseCompressionEdit(
                start_seconds=region.start_frame / sample_rate,
                original_ms=region.duration_ms,
                target_ms=actual_target_ms,
                removed_ms=region.duration_ms - actual_target_ms,
                context=context,
                preceding_word=preceding,
            )
        )
    output.extend(samples[cursor:])
    if edits:
        write_pcm16_mono(path, parameters, output)
    compressed_duration = len(output) / sample_rate
    return PauseCompressionReport(
        path=str(path),
        original_duration=original_duration,
        compressed_duration=compressed_duration,
        removed_duration=original_duration - compressed_duration,
        detected_pause_count=len(regions),
        compressed_pause_count=len(edits),
        edits=tuple(edits),
    )


def pause_statistics(durations: Sequence[float]) -> dict[str, float | int]:
    ordered = sorted(float(value) for value in durations)

    def percentile(percent: float) -> float:
        if not ordered:
            return 0.0
        rank = (len(ordered) - 1) * percent / 100.0
        low = math.floor(rank)
        high = math.ceil(rank)
        if low == high:
            return ordered[low]
        return ordered[low] + (rank - low) * (ordered[high] - ordered[low])

    total = sum(ordered)
    return {
        "count": len(ordered),
        "total": round(total, 6),
        "average": round(total / len(ordered), 6) if ordered else 0.0,
        "median": round(percentile(50), 6),
        "p90": round(percentile(90), 6),
        "p95": round(percentile(95), 6),
        "maximum": round(ordered[-1], 6) if ordered else 0.0,
        "over_300ms": sum(value > 0.3 for value in ordered),
    }
