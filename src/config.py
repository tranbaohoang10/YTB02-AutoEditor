from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import AutoEditorError


@dataclass(frozen=True)
class VideoConfig:
    width: int
    height: int
    fps: int
    codec: str
    crf: int
    preset: str


@dataclass(frozen=True)
class PauseProfile:
    comma_target_ms: int
    clause_target_ms: int
    sentence_target_ms: int
    neutral_medium_target_ms: int
    neutral_long_target_ms: int
    neutral_very_long_target_ms: int
    chunk_join_ms: int


@dataclass(frozen=True)
class AudioConfig:
    sample_rate: int
    mix_sample_rate: int
    aac_bitrate: str
    gap_ms: int
    narration_edge_silence_ms: int
    narration_silence_threshold_db: float
    smart_pause_compression: bool
    pause_threshold_db: float
    pause_min_detect_ms: int
    pause_short_max_ms: int
    pause_medium_max_ms: int
    pause_long_max_ms: int
    pause_medium_target_ms: int
    pause_long_target_ms: int
    pause_very_long_target_ms: int
    pause_edge_guard_ms: int
    pause_crossfade_ms: int
    pause_profiles: dict[str, PauseProfile]
    narration_mode: str
    continuous_chunk_scenes: int
    scene_tail_ms: int
    preserve_source_audio: bool
    source_audio_gain_db: float
    source_audio_fade_ms: int
    normalize_loudness: bool
    target_lufs: float
    true_peak_db: float
    lra: float


@dataclass(frozen=True)
class SubtitleConfig:
    font: str
    font_size: int
    margin_bottom: int
    outline: int
    max_chars_per_line: int
    max_lines: int
    max_words_per_window: int = 8
    min_words_per_phrase: int = 4
    max_words_per_phrase: int = 8
    min_hold_ms: int = 250
    max_hold_ms: int = 450
    cps_warning: float = 22.0


@dataclass(frozen=True)
class AlignmentConfig:
    engine: str
    device: str
    allow_approximate_fallback: bool
    model_en: str | None
    model_vi: str | None
    cache_dir: Path
    duration_tolerance: float


@dataclass(frozen=True)
class AppConfig:
    kokoro_python: Path
    ffmpeg: str
    ffprobe: str
    video: VideoConfig
    audio: AudioConfig
    subtitles: SubtitleConfig
    alignment: AlignmentConfig


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    if not isinstance(value, dict):
        raise AutoEditorError(f"config.json: thiếu section '{name}'.")
    return value


def load_config(path: Path) -> AppConfig:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AutoEditorError(f"Không tìm thấy config: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AutoEditorError(f"Không đọc được config.json: {exc}") from exc
    try:
        video = _section(data, "video")
        audio = _section(data, "audio")
        subtitles = _section(data, "subtitles")
        alignment = _section(data, "alignment")
        fallback_value = alignment["allow_approximate_fallback"]
        if not isinstance(fallback_value, bool):
            raise TypeError("alignment.allow_approximate_fallback phải là boolean")
        normalize_loudness = audio.get("normalize_loudness", True)
        if not isinstance(normalize_loudness, bool):
            raise TypeError("audio.normalize_loudness phải là boolean")
        preserve_source_audio = audio.get("preserve_source_audio", True)
        if not isinstance(preserve_source_audio, bool):
            raise TypeError("audio.preserve_source_audio phải là boolean")
        smart_pause_compression = audio.get("smart_pause_compression", True)
        if not isinstance(smart_pause_compression, bool):
            raise TypeError("audio.smart_pause_compression phải là boolean")
        kokoro_python = Path(str(data["kokoro_python"]))
        if not kokoro_python.is_absolute():
            kokoro_python = (path.parent / kokoro_python).resolve()
        raw_pause_profiles = audio.get("pause_profiles", {})
        if not isinstance(raw_pause_profiles, dict):
            raise TypeError("audio.pause_profiles phải là object")
        pause_profiles: dict[str, PauseProfile] = {}
        defaults = {
            "en": (210, 260, 320, 220, 270, 340, 320),
            "vi": (230, 280, 350, 240, 290, 370, 380),
        }
        for language, values in defaults.items():
            raw_profile = raw_pause_profiles.get(language, {})
            if not isinstance(raw_profile, dict):
                raise TypeError(f"audio.pause_profiles.{language} phải là object")
            names = (
                "comma_target_ms", "clause_target_ms", "sentence_target_ms",
                "neutral_medium_target_ms", "neutral_long_target_ms",
                "neutral_very_long_target_ms", "chunk_join_ms",
            )
            pause_profiles[language] = PauseProfile(**{
                name: int(raw_profile.get(name, default))
                for name, default in zip(names, values)
            })
        result = AppConfig(
            kokoro_python=kokoro_python,
            ffmpeg=str(data["ffmpeg"]),
            ffprobe=str(data["ffprobe"]),
            video=VideoConfig(
                width=int(video["width"]), height=int(video["height"]),
                fps=int(video["fps"]), codec=str(video["codec"]),
                crf=int(video["crf"]), preset=str(video["preset"]),
            ),
            audio=AudioConfig(
                sample_rate=int(audio["sample_rate"]),
                mix_sample_rate=int(audio.get("mix_sample_rate", 48000)),
                aac_bitrate=str(audio["aac_bitrate"]),
                gap_ms=int(audio["gap_ms"]),
                narration_edge_silence_ms=int(audio.get("narration_edge_silence_ms", 50)),
                narration_silence_threshold_db=float(
                    audio.get("narration_silence_threshold_db", -50.0)
                ),
                smart_pause_compression=smart_pause_compression,
                pause_threshold_db=float(audio.get("pause_threshold_db", -35.0)),
                pause_min_detect_ms=int(audio.get("pause_min_detect_ms", 120)),
                pause_short_max_ms=int(audio.get("pause_short_max_ms", 180)),
                pause_medium_max_ms=int(audio.get("pause_medium_max_ms", 350)),
                pause_long_max_ms=int(audio.get("pause_long_max_ms", 700)),
                pause_medium_target_ms=int(audio.get("pause_medium_target_ms", 220)),
                pause_long_target_ms=int(audio.get("pause_long_target_ms", 280)),
                pause_very_long_target_ms=int(
                    audio.get("pause_very_long_target_ms", 350)
                ),
                pause_edge_guard_ms=int(audio.get("pause_edge_guard_ms", 25)),
                pause_crossfade_ms=int(audio.get("pause_crossfade_ms", 8)),
                pause_profiles=pause_profiles,
                narration_mode=str(audio.get("narration_mode", "scene")),
                continuous_chunk_scenes=int(audio.get("continuous_chunk_scenes", 5)),
                scene_tail_ms=int(audio.get("scene_tail_ms", 100)),
                preserve_source_audio=preserve_source_audio,
                source_audio_gain_db=float(audio.get("source_audio_gain_db", -18.0)),
                source_audio_fade_ms=int(audio.get("source_audio_fade_ms", 120)),
                normalize_loudness=normalize_loudness,
                target_lufs=float(audio.get("target_lufs", -18.0)),
                true_peak_db=float(audio.get("true_peak_db", -1.5)),
                lra=float(audio.get("lra", 7.0)),
            ),
            subtitles=SubtitleConfig(
                font=str(subtitles["font"]), font_size=int(subtitles["font_size"]),
                margin_bottom=int(subtitles["margin_bottom"]),
                outline=int(subtitles["outline"]),
                max_chars_per_line=int(subtitles["max_chars_per_line"]),
                max_lines=int(subtitles["max_lines"]),
                max_words_per_window=int(subtitles.get("max_words_per_window", 8)),
                min_words_per_phrase=int(subtitles.get("min_words_per_phrase", 4)),
                max_words_per_phrase=int(subtitles.get("max_words_per_phrase", 8)),
                min_hold_ms=int(subtitles.get("min_hold_ms", 250)),
                max_hold_ms=int(subtitles.get("max_hold_ms", 450)),
                cps_warning=float(subtitles.get("cps_warning", 22.0)),
            ),
            alignment=AlignmentConfig(
                engine=str(alignment["engine"]),
                device=str(alignment["device"]),
                allow_approximate_fallback=fallback_value,
                model_en=(str(alignment["model_en"]) if alignment.get("model_en") else None),
                model_vi=(str(alignment["model_vi"]) if alignment.get("model_vi") else None),
                cache_dir=(path.parent / str(alignment["cache_dir"])).resolve()
                if not Path(str(alignment["cache_dir"])).is_absolute()
                else Path(str(alignment["cache_dir"])),
                duration_tolerance=float(alignment.get("duration_tolerance", 0.25)),
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AutoEditorError(f"config.json có giá trị thiếu hoặc không hợp lệ: {exc}") from exc
    if result.video.width <= 0 or result.video.height <= 0 or result.video.fps <= 0:
        raise AutoEditorError("Kích thước và FPS trong config phải lớn hơn 0.")
    if result.audio.sample_rate <= 0 or result.audio.mix_sample_rate <= 0:
        raise AutoEditorError("sample_rate và mix_sample_rate phải > 0.")
    if result.audio.gap_ms < 0 or result.audio.gap_ms > 150:
        raise AutoEditorError("gap_ms phải trong khoảng 0..150 ms.")
    if not 0 <= result.audio.narration_edge_silence_ms <= 150:
        raise AutoEditorError("narration_edge_silence_ms phải trong khoảng 0..150 ms.")
    if not -90.0 <= result.audio.narration_silence_threshold_db <= -20.0:
        raise AutoEditorError("narration_silence_threshold_db phải trong khoảng -90..-20 dB.")
    if not -90.0 <= result.audio.pause_threshold_db <= -20.0:
        raise AutoEditorError("pause_threshold_db phải trong khoảng -90..-20 dB.")
    if not 20 <= result.audio.pause_min_detect_ms <= 2000:
        raise AutoEditorError("pause_min_detect_ms phải trong khoảng 20..2000 ms.")
    if not (
        0 < result.audio.pause_short_max_ms
        < result.audio.pause_medium_max_ms
        < result.audio.pause_long_max_ms
    ):
        raise AutoEditorError("Các ngưỡng pause short/medium/long phải tăng dần.")
    targets = (
        result.audio.pause_medium_target_ms,
        result.audio.pause_long_target_ms,
        result.audio.pause_very_long_target_ms,
    )
    if any(target <= 0 for target in targets):
        raise AutoEditorError("Các pause target phải > 0 ms.")
    if result.audio.pause_medium_target_ms >= result.audio.pause_medium_max_ms:
        raise AutoEditorError("pause_medium_target_ms phải nhỏ hơn medium max.")
    if result.audio.pause_long_target_ms >= result.audio.pause_long_max_ms:
        raise AutoEditorError("pause_long_target_ms phải nhỏ hơn long max.")
    if not 0 <= result.audio.pause_edge_guard_ms <= 100:
        raise AutoEditorError("pause_edge_guard_ms phải trong khoảng 0..100 ms.")
    if not 0 <= result.audio.pause_crossfade_ms <= 50:
        raise AutoEditorError("pause_crossfade_ms phải trong khoảng 0..50 ms.")
    if min(targets) < 2 * (
        result.audio.pause_edge_guard_ms + result.audio.pause_crossfade_ms
    ):
        raise AutoEditorError("Pause target quá ngắn cho edge guard và crossfade.")
    minimum_safe_pause = 2 * (
        result.audio.pause_edge_guard_ms + result.audio.pause_crossfade_ms
    )
    for language, profile in result.audio.pause_profiles.items():
        profile_targets = (
            profile.comma_target_ms, profile.clause_target_ms,
            profile.sentence_target_ms, profile.neutral_medium_target_ms,
            profile.neutral_long_target_ms, profile.neutral_very_long_target_ms,
        )
        if any(target < minimum_safe_pause or target > 1000 for target in profile_targets):
            raise AutoEditorError(
                f"Pause profile {language} phải nằm trong {minimum_safe_pause}..1000 ms."
            )
        if not 100 <= profile.chunk_join_ms <= 1000:
            raise AutoEditorError(
                f"audio.pause_profiles.{language}.chunk_join_ms phải trong 100..1000 ms."
            )
    if result.audio.narration_mode not in {"scene", "continuous"}:
        raise AutoEditorError("audio.narration_mode chỉ hỗ trợ 'scene' hoặc 'continuous'.")
    if not 1 <= result.audio.continuous_chunk_scenes <= 30:
        raise AutoEditorError("continuous_chunk_scenes phải trong khoảng 1..30.")
    if not 0 <= result.audio.scene_tail_ms <= 500:
        raise AutoEditorError("scene_tail_ms phải trong khoảng 0..500 ms.")
    if not -60.0 <= result.audio.source_audio_gain_db <= 0.0:
        raise AutoEditorError("source_audio_gain_db phải trong khoảng -60..0 dB.")
    if not 0 <= result.audio.source_audio_fade_ms <= 2000:
        raise AutoEditorError("source_audio_fade_ms phải trong khoảng 0..2000 ms.")
    if not -70.0 <= result.audio.target_lufs <= -5.0:
        raise AutoEditorError("audio.target_lufs phải trong khoảng -70..-5 LUFS.")
    if not -9.0 <= result.audio.true_peak_db <= 0.0:
        raise AutoEditorError("audio.true_peak_db phải trong khoảng -9..0 dBTP.")
    if not 1.0 <= result.audio.lra <= 50.0:
        raise AutoEditorError("audio.lra phải trong khoảng 1..50 LU.")
    if result.alignment.engine != "whisperx":
        raise AutoEditorError("alignment.engine hiện chỉ hỗ trợ 'whisperx'.")
    if result.alignment.device != "cpu":
        raise AutoEditorError("MVP alignment chỉ hỗ trợ device='cpu'.")
    if result.alignment.duration_tolerance < 0:
        raise AutoEditorError("alignment.duration_tolerance không được âm.")
    if result.subtitles.max_lines < 1 or result.subtitles.max_words_per_window < 1:
        raise AutoEditorError("Subtitle max_lines và max_words_per_window phải >= 1.")
    if not 1 <= result.subtitles.min_words_per_phrase <= result.subtitles.max_words_per_phrase <= 12:
        raise AutoEditorError("Subtitle phrase word limits phải tăng dần trong 1..12.")
    if not 0 <= result.subtitles.min_hold_ms <= result.subtitles.max_hold_ms <= 2000:
        raise AutoEditorError("Subtitle hold phải tăng dần trong 0..2000 ms.")
    if result.subtitles.cps_warning <= 0:
        raise AutoEditorError("Subtitle cps_warning phải > 0.")
    return result
