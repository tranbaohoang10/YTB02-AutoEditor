from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Scene:
    id: int
    video: str
    text: str


@dataclass(frozen=True)
class Script:
    title: str
    language: str
    voice: str
    speed: float
    scenes: tuple[Scene, ...]


@dataclass(frozen=True)
class TimelineEntry:
    scene: Scene
    audio_path: Path
    duration: float
    start: float
    end: float


@dataclass(frozen=True)
class SubtitleCue:
    index: int
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class WordTiming:
    """One canonical display token and its scene-relative or global timing."""

    word: str
    start: float
    end: float


@dataclass(frozen=True)
class SceneAlignment:
    """Validated scene-relative word timings from forced alignment."""

    scene_id: int
    language: str
    words: tuple[WordTiming, ...]


class AutoEditorError(Exception):
    """Expected, user-facing pipeline error."""
