from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import Iterable

from .config import SubtitleConfig
from .models import SubtitleCue, TimelineEntry


_BOUNDARY = re.compile(r"(?<=[.!?;:…])\s+")


def format_srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def format_ass_timestamp(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, centiseconds = divmod(centiseconds, 360_000)
    minutes, centiseconds = divmod(centiseconds, 6_000)
    secs, centiseconds = divmod(centiseconds, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def _split_long_phrase(text: str, limit: int) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    max_chars = max(1, limit * 2)
    for word in words:
        candidate = " ".join((*current, word))
        if current and len(candidate) > max_chars:
            chunks.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        chunks.append(" ".join(current))
    return chunks


def split_subtitle_text(text: str, max_chars_per_line: int, max_lines: int) -> list[str]:
    limit = max(1, max_chars_per_line * max_lines)
    phrases = [part.strip() for part in _BOUNDARY.split(text.strip()) if part.strip()]
    chunks: list[str] = []
    current = ""
    for phrase in phrases:
        for part in _split_long_phrase(phrase, max_chars_per_line):
            candidate = f"{current} {part}".strip()
            if current and len(candidate) > limit:
                chunks.append(current)
                current = part
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks or [text.strip()]


def _wrap(text: str, width: int, max_lines: int) -> str:
    lines = textwrap.wrap(
        text, width=max(1, width), break_long_words=False, break_on_hyphens=False,
    )
    if len(lines) <= max_lines:
        return "\n".join(lines)
    # Chunking normally prevents this; preserve all text if a single very long word exists.
    return "\n".join(lines)


def create_cues(
    timeline: Iterable[TimelineEntry], config: SubtitleConfig
) -> tuple[SubtitleCue, ...]:
    cues: list[SubtitleCue] = []
    index = 1
    for entry in timeline:
        chunks = split_subtitle_text(
            entry.scene.text, config.max_chars_per_line, config.max_lines
        )
        weights = [max(1, len(re.sub(r"\s+", "", chunk))) for chunk in chunks]
        total_weight = sum(weights)
        cursor = entry.start
        for position, (chunk, weight) in enumerate(zip(chunks, weights)):
            end = (
                entry.end
                if position == len(chunks) - 1
                else cursor + entry.duration * weight / total_weight
            )
            cues.append(
                SubtitleCue(
                    index=index, start=cursor, end=end,
                    text=_wrap(chunk, config.max_chars_per_line, config.max_lines),
                )
            )
            cursor = end
            index += 1
    return tuple(cues)


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
