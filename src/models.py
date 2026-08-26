from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Scene:
    id: int
    video: str | None
    text: str
    image: str | None = None
    visual_hint: str | None = None
    image_prompt: str | None = None
    motion_type: str = "auto"
    assets: str | None = None


@dataclass(frozen=True)
class VisualSettings:
    mode: str = "auto"
    image_provider: str = "manual"
    image_model: str = "gemini-3.1-flash-image"
    style_preset: str = "newsprint-editorial"
    aspect_ratio: str = "16:9"
    image_size: str = "2K"
    motion_mode: str = "local"
    motion_provider: str | None = None
    motion_model: str = "veo-3.1-generate-preview"
    ai_fallback_local: bool = False


@dataclass(frozen=True)
class Script:
    title: str
    language: str
    voice: str
    speed: float
    scenes: tuple[Scene, ...]
    visual: VisualSettings = VisualSettings()
    topic: str = ""
    part: int = 1


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
class SubtitlePhrase:
    scene_id: int
    words: tuple["WordTiming", ...]
    line_break: int | None
    start: float
    end: float


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
