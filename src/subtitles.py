from __future__ import annotations

import math
import json
import textwrap
from pathlib import Path
from typing import Iterable, Sequence

from .config import SubtitleConfig
from .models import (
    AutoEditorError, SceneAlignment, SubtitleCue, SubtitlePhrase, TimelineEntry,
    WordTiming,
)
from .alignment import to_global_words


def format_srt_timestamp(seconds: float) -> str:
    # Ceiling prevents serialization precision from revealing a word early.
    milliseconds = max(0, math.ceil(seconds * 1000 - 1e-9))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def format_ass_timestamp(seconds: float) -> str:
    # ASS has centisecond precision: delay by <10ms rather than round backwards.
    centiseconds = max(0, math.ceil(seconds * 100 - 1e-9))
    hours, centiseconds = divmod(centiseconds, 360_000)
    minutes, centiseconds = divmod(centiseconds, 6_000)
    secs, centiseconds = divmod(centiseconds, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def _wrap(text: str, width: int, max_lines: int) -> str:
    lines = textwrap.wrap(
        text, width=max(1, width), break_long_words=False, break_on_hyphens=False,
    )
    return "\n".join(lines)


def _fits_window(words: Sequence[WordTiming], config: SubtitleConfig) -> bool:
    if len(words) > config.max_words_per_window:
        return False
    wrapped = _wrap(
        " ".join(word.word for word in words), config.max_chars_per_line, config.max_lines
    )
    return len(wrapped.splitlines()) <= config.max_lines


def _caption_windows(
    words: Sequence[WordTiming], config: SubtitleConfig
) -> list[list[WordTiming]]:
    windows: list[list[WordTiming]] = []
    current: list[WordTiming] = []
    for word in words:
        candidate = [*current, word]
        if current and not _fits_window(candidate, config):
            windows.append(current)
            current = [word]
        else:
            current = candidate
    if current:
        windows.append(current)
    return windows


_BAD_ENDINGS = {
    "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "at",
    "for", "with", "by", "from", "và", "hoặc", "nhưng", "của", "cho", "với",
    "từ", "tại", "trong", "một", "những", "các",
}


def _clean_token(word: str) -> str:
    return word.casefold().strip(".,;:!?…—–()[]{}\"'“”‘’")


def _layout_break(words: Sequence[WordTiming], config: SubtitleConfig) -> int | None:
    text = " ".join(word.word for word in words)
    if len(text) <= config.max_chars_per_line:
        return None
    candidates: list[tuple[int, int, int]] = []
    for split in range(1, len(words)):
        left = len(" ".join(word.word for word in words[:split]))
        right = len(" ".join(word.word for word in words[split:]))
        overflow = max(0, left - config.max_chars_per_line) + max(
            0, right - config.max_chars_per_line
        )
        candidates.append((overflow, abs(left - right), split))
    return min(candidates)[2] if candidates else None


def _phrase_windows(
    words: Sequence[WordTiming], config: SubtitleConfig,
) -> list[list[WordTiming]]:
    result: list[list[WordTiming]] = []
    cursor = 0
    maximum = min(config.max_words_per_phrase, config.max_words_per_window)
    minimum = min(config.min_words_per_phrase, maximum)
    while cursor < len(words):
        remaining = len(words) - cursor
        size = min(maximum, remaining)
        if remaining > maximum and remaining - size < minimum:
            size -= minimum - (remaining - size)
        if size > minimum:
            punctuated = [
                count for count in range(minimum, size + 1)
                if words[cursor + count - 1].word.rstrip().endswith(
                    (".", ",", ";", ":", "!", "?", "…", "—", "–")
                )
            ]
            if punctuated:
                size = max(punctuated)
        while size > minimum:
            candidate = words[cursor:cursor + size]
            split = _layout_break(candidate, config)
            lines = (
                [" ".join(word.word for word in candidate)] if split is None else
                [" ".join(word.word for word in candidate[:split]),
                 " ".join(word.word for word in candidate[split:])]
            )
            if max(map(len, lines)) <= config.max_chars_per_line:
                break
            size -= 1
        while size > minimum and _clean_token(words[cursor + size - 1].word) in _BAD_ENDINGS:
            size -= 1
        result.append(list(words[cursor:cursor + size]))
        cursor += size
    return result


def create_subtitle_phrases(
    alignments: Sequence[SceneAlignment], timeline: Sequence[TimelineEntry],
    config: SubtitleConfig,
) -> tuple[SubtitlePhrase, ...]:
    """Create fixed-layout phrases from final forced-alignment timestamps."""
    by_scene = {alignment.scene_id: alignment for alignment in alignments}
    phrases: list[SubtitlePhrase] = []
    for entry in timeline:
        alignment = by_scene.get(entry.scene.id)
        if alignment is None:
            raise AutoEditorError(f"Thiếu word alignment cho scene {entry.scene.id:02d}.")
        windows = _phrase_windows(to_global_words(alignment, entry.start), config)
        for index, window in enumerate(windows):
            boundary = windows[index + 1][0].start if index + 1 < len(windows) else entry.end
            last_end = window[-1].end
            desired_end = last_end + config.max_hold_ms / 1000.0
            end = min(boundary, desired_end)
            if end < last_end:
                raise AutoEditorError("Subtitle phrase kết thúc trước aligned word cuối.")
            phrases.append(SubtitlePhrase(
                scene_id=entry.scene.id, words=tuple(window),
                line_break=_layout_break(window, config),
                start=window[0].start, end=end,
            ))
    for left, right in zip(phrases, phrases[1:]):
        if left.end > right.start + 1e-9:
            raise AutoEditorError("Subtitle phrases bị overlap.")
    return tuple(phrases)


def _phrase_prefix(phrase: SubtitlePhrase, count: int) -> str:
    visible = phrase.words[:count]
    split = phrase.line_break
    if split is None or count <= split:
        return " ".join(word.word for word in visible)
    return (
        " ".join(word.word for word in visible[:split]) + "\n" +
        " ".join(word.word for word in visible[split:])
    )


def _window_cues(
    window: Sequence[WordTiming],
    window_end: float,
    config: SubtitleConfig,
) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    position = 0
    while position < len(window):
        event_start = window[position].start
        reveal_end = position + 1
        while reveal_end < len(window) and window[reveal_end].start == event_start:
            reveal_end += 1
        event_end = window[reveal_end].start if reveal_end < len(window) else window_end
        if event_end > event_start:
            text = " ".join(word.word for word in window[:reveal_end])
            cues.append(
                SubtitleCue(
                    index=0,
                    start=event_start,
                    end=event_end,
                    text=_wrap(text, config.max_chars_per_line, config.max_lines),
                )
            )
        position = reveal_end
    return cues


def create_rolling_cues(
    alignments: Sequence[SceneAlignment],
    timeline: Sequence[TimelineEntry],
    config: SubtitleConfig,
) -> tuple[SubtitleCue, ...]:
    """Create rolling events solely from validated forced-alignment timestamps."""
    cues: list[SubtitleCue] = []
    for phrase in create_subtitle_phrases(alignments, timeline, config):
        position = 0
        while position < len(phrase.words):
            start = phrase.words[position].start
            reveal_end = position + 1
            while reveal_end < len(phrase.words) and phrase.words[reveal_end].start == start:
                reveal_end += 1
            end = (
                phrase.words[reveal_end].start
                if reveal_end < len(phrase.words) else phrase.end
            )
            if end > start:
                cues.append(SubtitleCue(0, start, end, _phrase_prefix(phrase, reveal_end)))
            position = reveal_end

    ordered: list[SubtitleCue] = []
    for index, cue in enumerate(cues, 1):
        if ordered and cue.start < ordered[-1].end:
            raise AutoEditorError("Rolling subtitle events bị overlap hoặc sai thứ tự.")
        ordered.append(SubtitleCue(index, cue.start, cue.end, cue.text))
    return tuple(ordered)


def write_srt(cues: Iterable[SubtitleCue], path: Path) -> None:
    blocks = []
    for cue in cues:
        blocks.append(
            f"{cue.index}\n{format_srt_timestamp(cue.start)} --> "
            f"{format_srt_timestamp(cue.end)}\n{cue.text}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def _ass_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def write_ass(
    cues: Iterable[SubtitleCue], path: Path, config: SubtitleConfig,
    width: int, height: int,
) -> None:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{config.font},{config.font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,{config.outline},0,2,60,60,{config.margin_bottom},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = [
        f"Dialogue: 0,{format_ass_timestamp(cue.start)},{format_ass_timestamp(cue.end)},"
        f"Default,,0,0,0,,{_ass_escape(cue.text)}"
        for cue in cues
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")


def _phrase_ass_text(phrase: SubtitlePhrase) -> str:
    starts = [max(0, math.ceil(word.start * 100 - 1e-9)) for word in phrase.words]
    end_cs = max(starts[-1], math.ceil(phrase.end * 100 - 1e-9))
    parts: list[str] = []
    for index, word in enumerate(phrase.words):
        next_start = starts[index + 1] if index + 1 < len(starts) else end_cs
        duration = max(0, next_start - starts[index])
        if phrase.line_break == index:
            parts.append(r"\N")
        elif index:
            parts.append(" ")
        parts.append(r"{\ko" + str(duration) + "}" + _ass_escape(word.word))
    return "".join(parts)


def write_phrase_ass(
    phrases: Sequence[SubtitlePhrase], path: Path, config: SubtitleConfig,
    width: int, height: int,
) -> None:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{config.font},{config.font_size},&H00FFFFFF,&HFFFFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,{config.outline},0,2,60,60,{config.margin_bottom},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    for phrase in phrases:
        starts = [math.ceil(word.start * 100 - 1e-9) for word in phrase.words]
        if math.ceil(phrase.start * 100 - 1e-9) != starts[0]:
            raise AutoEditorError("ASS phrase không bắt đầu đúng serialized word start.")
        if any(left > right for left, right in zip(starts, starts[1:])):
            raise AutoEditorError("ASS word reveal không theo thứ tự alignment.")
        events.append(
            f"Dialogue: 0,{format_ass_timestamp(phrase.start)},"
            f"{format_ass_timestamp(phrase.end)},Default,,0,0,0,,"
            f"{_phrase_ass_text(phrase)}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")


def write_subtitle_diagnostics(
    phrases: Sequence[SubtitlePhrase], path: Path, config: SubtitleConfig,
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for index, phrase in enumerate(phrases, 1):
        text = " ".join(word.word for word in phrase.words)
        duration = max(0.001, phrase.end - phrase.start)
        hold = max(0.0, phrase.end - phrase.words[-1].end)
        lines = _phrase_prefix(phrase, len(phrase.words)).splitlines()
        cps = len(text) / duration
        records.append({
            "index": index, "scene_id": phrase.scene_id,
            "start": round(phrase.start, 6), "end": round(phrase.end, 6),
            "word_count": len(phrase.words), "characters": len(text),
            "duration": round(duration, 6), "cps": round(cps, 3),
            "hold_ms": round(hold * 1000), "line_count": len(lines),
            "max_line_chars": max(map(len, lines)),
            "cps_warning": cps > config.cps_warning,
            "short_phrase": len(phrase.words) < config.min_words_per_phrase,
            "text": text,
        })
    cps_values = sorted(float(item["cps"]) for item in records)
    def percentile(fraction: float) -> float:
        if not cps_values:
            return 0.0
        return cps_values[round((len(cps_values) - 1) * fraction)]
    payload: dict[str, object] = {
        "phrase_count": len(records),
        "cps": {
            "average": round(sum(cps_values) / len(cps_values), 3) if cps_values else 0.0,
            "p90": round(percentile(0.90), 3), "p95": round(percentile(0.95), 3),
            "maximum": round(max(cps_values), 3) if cps_values else 0.0,
            "over_warning": sum(value > config.cps_warning for value in cps_values),
            "warning_threshold": config.cps_warning,
        },
        "phrases": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
