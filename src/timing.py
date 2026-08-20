from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from .models import AutoEditorError, Scene, TimelineEntry


def build_timeline(
    scenes: Iterable[Scene],
    audio_dir: Path,
    duration_reader: Callable[[Path], float],
    gap_ms: int = 0,
) -> tuple[TimelineEntry, ...]:
    if gap_ms < 0:
        raise AutoEditorError("gap_ms không được âm.")
    entries: list[TimelineEntry] = []
    cursor = 0.0
    gap = gap_ms / 1000.0
    scene_list = list(scenes)
    for index, scene in enumerate(scene_list):
        audio_path = audio_dir / f"scene_{scene.id:03d}.wav"
        duration = duration_reader(audio_path)
        if duration <= 0:
            raise AutoEditorError(f"Audio scene {scene.id} rỗng hoặc duration không hợp lệ.")
        start = cursor
        end = start + duration
        entries.append(TimelineEntry(scene, audio_path, duration, start, end))
        cursor = end + (gap if index < len(scene_list) - 1 else 0.0)
    return tuple(entries)
