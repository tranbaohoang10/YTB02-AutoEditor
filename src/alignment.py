from __future__ import annotations

import json
import os
import re
import unicodedata
from numbers import Real
from pathlib import Path
from typing import Any, Protocol, Sequence

from .config import AlignmentConfig
from .models import (
    AutoEditorError,
    Scene,
    SceneAlignment,
    TimelineEntry,
    WordTiming,
)


_TOKEN_PATTERN = re.compile(r"\S+", re.UNICODE)


class AlignmentEngine(Protocol):
    def align(self, audio_path: Path, text: str, duration: float) -> Sequence[dict[str, Any]]:
        """Return WhisperX-like word segments with word/start/end keys."""


def canonical_words(text: str) -> tuple[str, ...]:
    """Return alignable display tokens while preserving standalone punctuation.

    Punctuation-only whitespace tokens are not spoken words. They attach to the
    previous spoken token, or to the next token when they occur at the start.
    """
    raw_tokens = _TOKEN_PATTERN.findall(text)
    display_tokens: list[str] = []
    leading_punctuation: list[str] = []
    for token in raw_tokens:
        if _normalized_word(token):
            if leading_punctuation:
                token = " ".join((*leading_punctuation, token))
                leading_punctuation.clear()
            display_tokens.append(token)
        elif display_tokens:
            display_tokens[-1] = f"{display_tokens[-1]} {token}"
        else:
            leading_punctuation.append(token)
    if leading_punctuation:
        if display_tokens:
            display_tokens[-1] = f"{display_tokens[-1]} {' '.join(leading_punctuation)}"
        else:
            raise AutoEditorError("Canonical transcript chỉ chứa punctuation, không có spoken word.")
    return tuple(display_tokens)


def _normalized_word(word: str) -> str:
    normalized = unicodedata.normalize("NFKC", word).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _raw_alignable_words(
    raw_words: Sequence[dict[str, Any]],
) -> list[tuple[str, str, float | None, float | None]]:
    result: list[tuple[str, str, float | None, float | None]] = []
    for item in raw_words:
        display = str(item.get("word", "")).strip()
        normalized = _normalized_word(display)
        if not normalized:
            continue
        start = item.get("start")
        end = item.get("end")
        result.append(
            (
                display,
                normalized,
                float(start) if isinstance(start, Real) else None,
                float(end) if isinstance(end, Real) else None,
            )
        )
    return result


def validate_and_map_words(
    text: str,
    raw_words: Sequence[dict[str, Any]],
    audio_duration: float,
    tolerance: float,
) -> tuple[WordTiming, ...]:
    """Map aligner output back to canonical tokens and reject incomplete alignment."""
    canonical = canonical_words(text)
    if not canonical:
        raise AutoEditorError("Canonical transcript không có word để align.")
    raw = _raw_alignable_words(raw_words)
    mapped: list[WordTiming] = []
    raw_index = 0
    previous_start = -1.0

    for canonical_word in canonical:
        target = _normalized_word(canonical_word)
        if not target:  # Defensive: canonical_words() already attaches punctuation-only tokens.
            raise AutoEditorError(f"Canonical token {canonical_word!r} không thể forced-align.")
        combined = ""
        consumed: list[tuple[str, str, float | None, float | None]] = []
        while raw_index < len(raw) and len(combined) < len(target):
            candidate = combined + raw[raw_index][1]
            if not target.startswith(candidate):
                break
            consumed.append(raw[raw_index])
            combined = candidate
            raw_index += 1
        if combined != target or not consumed:
            raise AutoEditorError(
                f"Canonical word {canonical_word!r} không khớp aligned word tại vị trí {len(mapped) + 1}."
            )
        start = consumed[0][2]
        end = consumed[-1][3]
        if start is None or end is None:
            raise AutoEditorError(f"Canonical word {canonical_word!r} thiếu start/end timestamp.")
        if start < 0 or end < start:
            raise AutoEditorError(f"Timestamp không hợp lệ cho canonical word {canonical_word!r}.")
        if start < previous_start:
            raise AutoEditorError("Word alignment timestamps không theo thứ tự tăng dần.")
        if start > audio_duration:
            raise AutoEditorError(
                f"Word {canonical_word!r} bắt đầu sau scene audio duration ({start:.3f}s > {audio_duration:.3f}s)."
            )
        if end > audio_duration + tolerance:
            raise AutoEditorError(
                f"Word {canonical_word!r} kết thúc sau scene audio duration ({end:.3f}s > {audio_duration:.3f}s)."
            )
        mapped.append(WordTiming(canonical_word, start, end))
        previous_start = start

    if raw_index != len(raw):
        extras = " ".join(item[0] for item in raw[raw_index:])
        raise AutoEditorError(f"Aligner trả thêm word không có trong canonical script: {extras}")
    return tuple(mapped)


def to_global_words(alignment: SceneAlignment, offset: float) -> tuple[WordTiming, ...]:
    return tuple(
        WordTiming(word.word, word.start + offset, word.end + offset)
        for word in alignment.words
    )


def _canonical_count(text: str) -> int:
    try:
        return len(canonical_words(text))
    except AutoEditorError:
        return 0


class WhisperXAlignmentEngine:
    """One language-specific WhisperX model, loaded once and reused for all scenes."""

    def __init__(self, language: str, config: AlignmentConfig) -> None:
        config.cache_dir.mkdir(parents=True, exist_ok=True)
        nltk_cache = config.cache_dir / "nltk_data"
        nltk_cache.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("NLTK_DATA", str(nltk_cache))
        try:
            import whisperx
        except ImportError as exc:
            raise AutoEditorError(
                "Không import được whisperx. Hãy chạy SETUP.bat trong project."
            ) from exc
        model_name = config.model_en if language == "en" else config.model_vi
        try:
            self._model, self._metadata = whisperx.load_align_model(
                language_code=language,
                device=config.device,
                model_name=model_name,
                model_dir=str(config.cache_dir),
            )
        except Exception as exc:
            raise AutoEditorError(f"Không load được WhisperX alignment model ({language}): {exc}") from exc
        self._whisperx = whisperx
        self._device = config.device

    def align(self, audio_path: Path, text: str, duration: float) -> Sequence[dict[str, Any]]:
        transcript = [{"text": text, "start": 0.0, "end": duration}]
        try:
            audio = self._whisperx.load_audio(str(audio_path))
            result = self._whisperx.align(
                transcript,
                self._model,
                self._metadata,
                audio,
                self._device,
                interpolate_method="ignore",
                return_char_alignments=False,
                print_progress=False,
            )
        except Exception as exc:
            raise AutoEditorError(f"WhisperX forced alignment failed: {exc}") from exc
        words = result.get("word_segments")
        if not isinstance(words, list):
            raise AutoEditorError("WhisperX không trả về word_segments hợp lệ.")
        return words


def _write_diagnostics(
    path: Path,
    entry: TimelineEntry,
    language: str,
    status: str,
    words: Sequence[WordTiming],
    error: str | None = None,
    raw_words: Sequence[dict[str, Any]] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "scene_id": entry.scene.id,
        "language": language,
        "status": status,
        "canonical_text": entry.scene.text,
        "audio_duration": round(entry.duration, 6),
        "timeline_start": round(entry.start, 6),
        "timeline_end": round(entry.end, 6),
        "aligned_count": len(words),
        "canonical_count": _canonical_count(entry.scene.text),
        "words": [
            {"word": word.word, "start": round(word.start, 6), "end": round(word.end, 6)}
            for word in words
        ],
    }
    if error:
        payload["error"] = error
    if raw_words is not None and status != "ok":
        payload["raw_words"] = list(raw_words)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=lambda value: value.item() if hasattr(value, "item") else str(value),
        ),
        encoding="utf-8",
    )


def align_timeline(
    timeline: Sequence[TimelineEntry],
    language: str,
    config: AlignmentConfig,
    alignment_dir: Path,
    engine: AlignmentEngine | None = None,
) -> tuple[SceneAlignment, ...]:
    """Forced-align every scene with one reusable language model."""
    if config.allow_approximate_fallback:
        raise AutoEditorError(
            "Approximate alignment fallback không được triển khai; hãy đặt allow_approximate_fallback=false."
        )
    alignment_dir.mkdir(parents=True, exist_ok=True)
    active_engine = engine or WhisperXAlignmentEngine(language, config)
    results: list[SceneAlignment] = []
    for entry in timeline:
        diagnostics_path = alignment_dir / f"scene_{entry.scene.id:03d}.json"
        raw_words: Sequence[dict[str, Any]] = []
        try:
            raw_words = active_engine.align(entry.audio_path, entry.scene.text, entry.duration)
            words = validate_and_map_words(
                entry.scene.text, raw_words, entry.duration, config.duration_tolerance
            )
            alignment = SceneAlignment(entry.scene.id, language, words)
            _write_diagnostics(diagnostics_path, entry, language, "ok", words)
            results.append(alignment)
        except AutoEditorError as exc:
            _write_diagnostics(
                diagnostics_path, entry, language, "failed", (), str(exc), raw_words
            )
            aligned_count = sum(
                1 for item in raw_words
                if _normalized_word(str(item.get("word", "")))
                and isinstance(item.get("start"), Real)
                and isinstance(item.get("end"), Real)
            )
            canonical_count = _canonical_count(entry.scene.text)
            raise AutoEditorError(
                f"Word alignment failed for scene {entry.scene.id:02d}. "
                f"Aligned {aligned_count}/{canonical_count} canonical words. "
                f"See {diagnostics_path}\nReason: {exc}"
            ) from exc
    return tuple(results)


def align_continuous_narration(
    scenes: Sequence[Scene], audio_path: Path, audio_duration: float,
    language: str, config: AlignmentConfig, alignment_dir: Path,
    engine: AlignmentEngine | None = None,
) -> tuple[tuple[TimelineEntry, ...], tuple[SceneAlignment, ...]]:
    """Align one canonical narration master and map every word to one scene."""
    if config.allow_approximate_fallback:
        raise AutoEditorError(
            "Approximate alignment fallback không được triển khai; "
            "hãy đặt allow_approximate_fallback=false."
        )
    if not scenes:
        raise AutoEditorError("Continuous narration cần ít nhất một scene.")
    alignment_dir.mkdir(parents=True, exist_ok=True)
    full_text = " ".join(scene.text for scene in scenes)
    active_engine = engine or WhisperXAlignmentEngine(language, config)
    raw_words: Sequence[dict[str, Any]] = []
    try:
        raw_words = active_engine.align(audio_path, full_text, audio_duration)
        global_words = validate_and_map_words(
            full_text, raw_words, audio_duration, config.duration_tolerance
        )
    except AutoEditorError as exc:
        (alignment_dir / "continuous_master.json").write_text(
            json.dumps(
                {
                    "status": "failed",
                    "canonical_text": full_text,
                    "audio_duration": round(audio_duration, 6),
                    "canonical_count": _canonical_count(full_text),
                    "error": str(exc),
                    "raw_words": list(raw_words),
                },
                ensure_ascii=False,
                indent=2,
                default=lambda value: value.item() if hasattr(value, "item") else str(value),
            ),
            encoding="utf-8",
        )
        raise AutoEditorError(
            "Word alignment failed for continuous narration. "
            f"See {alignment_dir / 'continuous_master.json'}\nReason: {exc}"
        ) from exc

    owned: list[tuple[WordTiming, ...]] = []
    cursor = 0
    for scene in scenes:
        count = len(canonical_words(scene.text))
        words = tuple(global_words[cursor:cursor + count])
        if len(words) != count:
            raise AutoEditorError(
                f"Continuous alignment thiếu word cho scene {scene.id:02d}."
            )
        owned.append(words)
        cursor += count
    if cursor != len(global_words):
        raise AutoEditorError("Continuous alignment còn word chưa có scene ownership.")

    starts = [0.0]
    starts.extend(words[0].start for words in owned[1:])
    ends = [*starts[1:], audio_duration]
    timeline: list[TimelineEntry] = []
    alignments: list[SceneAlignment] = []
    for scene, words, start, end in zip(scenes, owned, starts, ends):
        if end <= start or words[-1].end > end + config.duration_tolerance:
            raise AutoEditorError(
                f"Continuous scene {scene.id:02d} có timing không hợp lệ "
                f"({start:.3f}..{end:.3f})."
            )
        entry = TimelineEntry(scene, audio_path, end - start, start, end)
        relative = tuple(
            WordTiming(word.word, word.start - start, word.end - start)
            for word in words
        )
        alignment = SceneAlignment(scene.id, language, relative)
        timeline.append(entry)
        alignments.append(alignment)
        _write_diagnostics(
            alignment_dir / f"scene_{scene.id:03d}.json",
            entry, language, "ok", relative,
        )

    (alignment_dir / "continuous_master.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "canonical_text": full_text,
                "audio_duration": round(audio_duration, 6),
                "canonical_count": len(global_words),
                "aligned_count": len(global_words),
                "scene_count": len(scenes),
                "scene_word_counts": {
                    str(scene.id): len(words) for scene, words in zip(scenes, owned)
                },
                "words": [
                    {
                        "word": word.word,
                        "start": round(word.start, 6),
                        "end": round(word.end, 6),
                    }
                    for word in global_words
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return tuple(timeline), tuple(alignments)
