from __future__ import annotations

import math
import textwrap
from pathlib import Path
from typing import Iterable, Sequence

from .config import SubtitleConfig
from .models import AutoEditorError, SceneAlignment, SubtitleCue, TimelineEntry, WordTiming
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
    by_scene = {alignment.scene_id: alignment for alignment in alignments}
    cues: list[SubtitleCue] = []
    for entry in timeline:
        alignment = by_scene.get(entry.scene.id)
        if alignment is None:
            raise AutoEditorError(f"Thiếu word alignment cho scene {entry.scene.id:02d}.")
        global_words = to_global_words(alignment, entry.start)
        windows = _caption_windows(global_words, config)
        for window_index, window in enumerate(windows):
            window_end = (
                windows[window_index + 1][0].start
                if window_index + 1 < len(windows)
                else entry.end
            )
            cues.extend(_window_cues(window, window_end, config))

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
