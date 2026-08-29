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
    bold: bool = False
    shadow: int = 0
    margin_horizontal: int = 60


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
class WatermarkConfig:
    enabled: bool
    position: str
    logo_file: Path
    logo_width: int
    logo_opacity: float
    margin_right: int
    margin_bottom: int
    shadow_x: int
    shadow_y: int
    shadow_opacity: float
    shadow_blur: float


@dataclass(frozen=True)
class SourceCleanupConfig:
    enabled: bool
    strategy: str
    target: str
    x_ratio: float
    y_ratio: float
    width_ratio: float
    height_ratio: float
    median_radius: int
    feather_px: int
    paper_margin_px: int
    crop_width_ratio: float
    crop_height_ratio: float
    cover_logo_width: int
    cover_logo_opacity: float
    cover_margin_right: int
    cover_margin_bottom: int
    cover_nudge_left: int
    cover_nudge_up: int


@dataclass(frozen=True)
class VisualQualityConfig:
    enabled: bool
    analysis_width: int
    sample_frames: int
    low_motion_threshold: float
    high_density_threshold: float
    micro_motion_zoom: float
    hierarchy_contrast: float
    hierarchy_saturation: float
    hierarchy_brightness: float
    hierarchy_vignette_angle: float
    subtitle_density_threshold: float


@dataclass(frozen=True)
class TransitionConfig:
    pause_aware: bool
    micro_pause_ms: int
    minimum_pause_ms: int
    preferred_trigger_ms: int
    strong_trigger_ms: int
    micro_transition_min_ms: int
    micro_transition_max_ms: int
    minimum_transition_ms: int
    max_transition_ms: int
    transition_ratio: float
    pre_roll_ratio: float
    settle_ms: int
    freeze_tail_motion_start_ms: int
    enable_visual: bool
    enable_sfx: bool
    style: str
    sfx_dir: Path
    sfx_gain_db: float
    sfx_fade_ms: int
    source_conflict_threshold_db: float


@dataclass(frozen=True)
class AppConfig:
    kokoro_python: Path
    ffmpeg: str
    ffprobe: str
    video: VideoConfig
    audio: AudioConfig
    subtitles: SubtitleConfig
    alignment: AlignmentConfig
    source_cleanup: SourceCleanupConfig
    visual_quality: VisualQualityConfig
    watermark: WatermarkConfig
    transitions: TransitionConfig


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
        watermark = _section(data, "watermark")
        transitions = _section(data, "transitions")
        source_cleanup = data.get("source_cleanup", {})
        visual_quality = data.get("visual_quality", {})
        if not isinstance(source_cleanup, dict):
            raise TypeError("source_cleanup phải là object")
        if not isinstance(visual_quality, dict):
            raise TypeError("visual_quality phải là object")
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
        subtitle_bold = subtitles.get("bold", False)
        if not isinstance(subtitle_bold, bool):
            raise TypeError("subtitles.bold phải là boolean")
        watermark_enabled = watermark.get("enabled", True)
        source_cleanup_enabled = source_cleanup.get("enabled", False)
        visual_quality_enabled = visual_quality.get("enabled", True)
        transition_pause_aware = transitions.get("pause_aware", True)
        transition_visual = transitions.get("enable_visual", True)
        transition_sfx = transitions.get("enable_sfx", True)
        for label, value in (
            ("watermark.enabled", watermark_enabled),
            ("source_cleanup.enabled", source_cleanup_enabled),
            ("visual_quality.enabled", visual_quality_enabled),
            ("transitions.pause_aware", transition_pause_aware),
            ("transitions.enable_visual", transition_visual),
            ("transitions.enable_sfx", transition_sfx),
        ):
            if not isinstance(value, bool):
                raise TypeError(f"{label} phải là boolean")
        kokoro_python = Path(str(data["kokoro_python"]))
        if not kokoro_python.is_absolute():
            kokoro_python = (path.parent / kokoro_python).resolve()
        watermark_logo_file = Path(str(watermark.get(
            "logo_file", "assets/branding/l0ki_archives_logo.png"
        )))
        if not watermark_logo_file.is_absolute():
            watermark_logo_file = (path.parent / watermark_logo_file).resolve()
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
                bold=subtitle_bold,
                shadow=int(subtitles.get("shadow", 0)),
                margin_horizontal=int(subtitles.get("margin_horizontal", 60)),
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
            source_cleanup=SourceCleanupConfig(
                enabled=source_cleanup_enabled,
                strategy=str(source_cleanup.get(
                    "strategy", "frequency_selective_reconstruct"
                )),
                target=str(source_cleanup.get("target", "gemini_flow_sparkle")),
                x_ratio=float(source_cleanup.get("x_ratio", 0.875)),
                y_ratio=float(source_cleanup.get("y_ratio", 0.764)),
                width_ratio=float(source_cleanup.get("width_ratio", 0.104167)),
                height_ratio=float(source_cleanup.get("height_ratio", 0.185185)),
                median_radius=int(source_cleanup.get("median_radius", 30)),
                feather_px=int(source_cleanup.get("feather_px", 3)),
                paper_margin_px=int(source_cleanup.get("paper_margin_px", 14)),
                crop_width_ratio=float(
                    source_cleanup.get("crop_width_ratio", 0.885416667)
                ),
                crop_height_ratio=float(
                    source_cleanup.get("crop_height_ratio", 0.885185185)
                ),
                cover_logo_width=int(source_cleanup.get("cover_logo_width", 110)),
                cover_logo_opacity=float(
                    source_cleanup.get("cover_logo_opacity", 0.42)
                ),
                cover_margin_right=int(source_cleanup.get("cover_margin_right", 14)),
                cover_margin_bottom=int(source_cleanup.get("cover_margin_bottom", 14)),
                cover_nudge_left=int(source_cleanup.get("cover_nudge_left", 111)),
                cover_nudge_up=int(source_cleanup.get("cover_nudge_up", 112)),
            ),
            visual_quality=VisualQualityConfig(
                enabled=visual_quality_enabled,
                analysis_width=int(visual_quality.get("analysis_width", 320)),
                sample_frames=int(visual_quality.get("sample_frames", 6)),
                low_motion_threshold=float(
                    visual_quality.get("low_motion_threshold", 0.09)
                ),
                high_density_threshold=float(
                    visual_quality.get("high_density_threshold", 0.064)
                ),
                micro_motion_zoom=float(visual_quality.get("micro_motion_zoom", 0.010)),
                hierarchy_contrast=float(
                    visual_quality.get("hierarchy_contrast", 0.97)
                ),
                hierarchy_saturation=float(
                    visual_quality.get("hierarchy_saturation", 0.92)
                ),
                hierarchy_brightness=float(
                    visual_quality.get("hierarchy_brightness", 0.008)
                ),
                hierarchy_vignette_angle=float(
                    visual_quality.get("hierarchy_vignette_angle", 0.448799)
                ),
                subtitle_density_threshold=float(
                    visual_quality.get("subtitle_density_threshold", 0.070)
                ),
            ),
            watermark=WatermarkConfig(
                enabled=watermark_enabled,
                position=str(watermark.get("position", "bottom_right")),
                logo_file=watermark_logo_file,
                logo_width=int(watermark.get("logo_width", 76)),
                logo_opacity=float(watermark.get("logo_opacity", 0.64)),
                margin_right=int(watermark.get("margin_right", 20)),
                margin_bottom=int(watermark.get("margin_bottom", 20)),
                shadow_x=int(watermark.get("shadow_x", 1)),
                shadow_y=int(watermark.get("shadow_y", 1)),
                shadow_opacity=float(watermark.get("shadow_opacity", 0.16)),
                shadow_blur=float(watermark.get("shadow_blur", 0.45)),
            ),
            transitions=TransitionConfig(
                pause_aware=transition_pause_aware,
                micro_pause_ms=int(transitions.get("micro_pause_ms", 180)),
                minimum_pause_ms=int(transitions.get("minimum_pause_ms", 250)),
                preferred_trigger_ms=int(transitions.get("preferred_trigger_ms", 300)),
                strong_trigger_ms=int(transitions.get("strong_trigger_ms", 450)),
                micro_transition_min_ms=int(
                    transitions.get("micro_transition_min_ms", 140)
                ),
                micro_transition_max_ms=int(
                    transitions.get("micro_transition_max_ms", 180)
                ),
                minimum_transition_ms=int(
                    transitions.get("minimum_transition_ms", 180)
                ),
                max_transition_ms=int(transitions.get("max_transition_ms", 350)),
                transition_ratio=float(transitions.get("transition_ratio", 0.72)),
                pre_roll_ratio=float(transitions.get("pre_roll_ratio", 0.15)),
                settle_ms=int(transitions.get("settle_ms", 33)),
                freeze_tail_motion_start_ms=int(
                    transitions.get("freeze_tail_motion_start_ms", 250)
                ),
                enable_visual=transition_visual,
                enable_sfx=transition_sfx,
                style=str(transitions.get("style", "paper_documentary")),
                sfx_dir=(path.parent / str(transitions.get("sfx_dir", "assets/sfx"))).resolve()
                if not Path(str(transitions.get("sfx_dir", "assets/sfx"))).is_absolute()
                else Path(str(transitions.get("sfx_dir", "assets/sfx"))),
                sfx_gain_db=float(transitions.get("sfx_gain_db", -19.0)),
                sfx_fade_ms=int(transitions.get("sfx_fade_ms", 30)),
                source_conflict_threshold_db=float(
                    transitions.get("source_conflict_threshold_db", -40.0)
                ),
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
    if not 0 <= result.subtitles.shadow <= 10:
        raise AutoEditorError("Subtitle shadow phải trong khoảng 0..10.")
    if not 0 <= result.subtitles.margin_horizontal <= result.video.width // 3:
        raise AutoEditorError("Subtitle margin_horizontal không hợp lệ.")
    cleanup = result.source_cleanup
    if cleanup.strategy not in {
        "frequency_selective_reconstruct",
        "cover_with_official_logo",
        "masked_median_blend", "paper_corner_patch", "safe_edge_crop",
        "median_texture_patch",
    }:
        raise AutoEditorError(
            "source_cleanup.strategy chỉ hỗ trợ frequency_selective_reconstruct/"
            "cover_with_official_logo/masked_median_blend/"
            "paper_corner_patch/safe_edge_crop/"
            "median_texture_patch."
        )
    if cleanup.target != "gemini_flow_sparkle":
        raise AutoEditorError("source_cleanup.target hiện chỉ hỗ trợ gemini_flow_sparkle.")
    if not all(0.0 <= value <= 1.0 for value in (
        cleanup.x_ratio, cleanup.y_ratio, cleanup.width_ratio, cleanup.height_ratio,
    )):
        raise AutoEditorError("Source-cleanup ratios phải nằm trong 0..1.")
    if cleanup.x_ratio + cleanup.width_ratio > 1.0 + 1e-6 or (
        cleanup.y_ratio + cleanup.height_ratio > 1.0 + 1e-6
    ):
        raise AutoEditorError("Source-cleanup patch phải nằm trong khung hình.")
    if not 1 <= cleanup.median_radius <= 127 or not 0 <= cleanup.feather_px <= 20:
        raise AutoEditorError("Source-cleanup median/feather không hợp lệ.")
    if not 4 <= cleanup.paper_margin_px <= 64:
        raise AutoEditorError("Source-cleanup paper_margin_px phải trong 4..64.")
    if not 0.5 <= cleanup.crop_width_ratio <= 1.0 or not (
        0.5 <= cleanup.crop_height_ratio <= 1.0
    ):
        raise AutoEditorError("Source-cleanup crop ratios phải trong 0.5..1.0.")
    if not 76 <= cleanup.cover_logo_width <= 160:
        raise AutoEditorError("source_cleanup.cover_logo_width phải trong 76..160.")
    if not 0.35 <= cleanup.cover_logo_opacity <= 0.50:
        raise AutoEditorError("source_cleanup.cover_logo_opacity phải trong 0.35..0.50.")
    if min(
        cleanup.cover_margin_right, cleanup.cover_margin_bottom,
        cleanup.cover_nudge_left, cleanup.cover_nudge_up,
    ) < 0:
        raise AutoEditorError("Source-cover margins/nudges không được âm.")
    quality = result.visual_quality
    if not 80 <= quality.analysis_width <= 960 or not 2 <= quality.sample_frames <= 30:
        raise AutoEditorError("Visual-quality analysis_width/sample_frames không hợp lệ.")
    if not 0.0 <= quality.low_motion_threshold <= 1.0:
        raise AutoEditorError("low_motion_threshold phải trong 0..1.")
    if not 0.0 <= quality.high_density_threshold <= 1.0:
        raise AutoEditorError("high_density_threshold phải trong 0..1.")
    if not 0.0 <= quality.micro_motion_zoom <= 0.05:
        raise AutoEditorError("micro_motion_zoom phải trong 0..0.05.")
    if not 0.8 <= quality.hierarchy_contrast <= 1.2:
        raise AutoEditorError("hierarchy_contrast phải trong 0.8..1.2.")
    if not 0.0 <= quality.hierarchy_saturation <= 2.0:
        raise AutoEditorError("hierarchy_saturation phải trong 0..2.")
    if not -0.1 <= quality.hierarchy_brightness <= 0.1:
        raise AutoEditorError("hierarchy_brightness phải trong -0.1..0.1.")
    if not 0.1 <= quality.hierarchy_vignette_angle <= 1.2:
        raise AutoEditorError("hierarchy_vignette_angle phải trong 0.1..1.2.")
    if not 0.0 <= quality.subtitle_density_threshold <= 1.0:
        raise AutoEditorError("subtitle_density_threshold phải trong 0..1.")
    if result.watermark.position != "bottom_right":
        raise AutoEditorError("watermark.position hiện chỉ hỗ trợ 'bottom_right'.")
    if not result.watermark.logo_file.is_file():
        raise AutoEditorError(
            f"Không tìm thấy watermark.logo_file: {result.watermark.logo_file}"
        )
    official_logo = (path.parent / "assets/branding/l0ki_archives_logo.png").resolve()
    if (
        cleanup.strategy == "cover_with_official_logo"
        and result.watermark.logo_file != official_logo
    ):
        raise AutoEditorError(
            "cover_with_official_logo chỉ được dùng asset chính thức "
            "assets/branding/l0ki_archives_logo.png."
        )
    if cleanup.strategy == "cover_with_official_logo" and not result.watermark.enabled:
        raise AutoEditorError(
            "cover_with_official_logo yêu cầu watermark.enabled=true để che source mark."
        )
    if not 12 <= result.watermark.logo_width <= 256:
        raise AutoEditorError("watermark.logo_width phải trong khoảng 12..256.")
    if not 0.55 <= result.watermark.logo_opacity <= 0.70:
        raise AutoEditorError("watermark.logo_opacity phải trong khoảng 0.55..0.70.")
    if min(result.watermark.margin_right, result.watermark.margin_bottom) < 0:
        raise AutoEditorError("Watermark margins không được âm.")
    if not -4 <= result.watermark.shadow_x <= 4:
        raise AutoEditorError("watermark.shadow_x phải trong khoảng -4..4.")
    if not -4 <= result.watermark.shadow_y <= 4:
        raise AutoEditorError("watermark.shadow_y phải trong khoảng -4..4.")
    if not 0.0 <= result.watermark.shadow_opacity <= 0.40:
        raise AutoEditorError("watermark.shadow_opacity phải trong khoảng 0..0.40.")
    if not 0.0 <= result.watermark.shadow_blur <= 3.0:
        raise AutoEditorError("watermark.shadow_blur phải trong khoảng 0..3.")
    if result.transitions.style != "paper_documentary":
        raise AutoEditorError("transitions.style hiện chỉ hỗ trợ 'paper_documentary'.")
    pause_thresholds = (
        result.transitions.minimum_pause_ms,
        result.transitions.preferred_trigger_ms,
        result.transitions.strong_trigger_ms,
    )
    if not 0 < pause_thresholds[0] <= pause_thresholds[1] <= pause_thresholds[2]:
        raise AutoEditorError("Các ngưỡng pause transition phải tăng dần và > 0.")
    if not 0 < result.transitions.micro_pause_ms <= result.transitions.minimum_pause_ms:
        raise AutoEditorError("micro_pause_ms phải > 0 và không vượt minimum_pause_ms.")
    if not (
        1 <= result.transitions.micro_transition_min_ms
        <= result.transitions.micro_transition_max_ms
        <= result.transitions.minimum_transition_ms
    ):
        raise AutoEditorError("Transition micro phải tăng dần và không vượt minimum_transition_ms.")
    if not (
        1 <= result.transitions.minimum_transition_ms
        <= result.transitions.max_transition_ms
        <= 1000
    ):
        raise AutoEditorError("Transition duration phải tăng dần trong 1..1000 ms.")
    if result.transitions.minimum_transition_ms > result.transitions.minimum_pause_ms:
        raise AutoEditorError("minimum_transition_ms không được vượt minimum_pause_ms.")
    if not 0.5 <= result.transitions.transition_ratio <= 0.85:
        raise AutoEditorError("transition_ratio phải trong khoảng 0.5..0.85.")
    if not 0.10 <= result.transitions.pre_roll_ratio <= 0.35:
        raise AutoEditorError("pre_roll_ratio phải trong khoảng 0.10..0.35.")
    if not 0 <= result.transitions.settle_ms <= 150:
        raise AutoEditorError("settle_ms phải trong khoảng 0..150 ms.")
    if not 0 <= result.transitions.freeze_tail_motion_start_ms <= 900:
        raise AutoEditorError("freeze_tail_motion_start_ms phải trong khoảng 0..900 ms.")
    if not -60.0 <= result.transitions.sfx_gain_db <= 0.0:
        raise AutoEditorError("transitions.sfx_gain_db phải trong khoảng -60..0 dB.")
    if not 0 <= result.transitions.sfx_fade_ms <= 250:
        raise AutoEditorError("transitions.sfx_fade_ms phải trong khoảng 0..250 ms.")
    if not -90.0 <= result.transitions.source_conflict_threshold_db <= 0.0:
        raise AutoEditorError(
            "transitions.source_conflict_threshold_db phải trong khoảng -90..0 dB."
        )
    return result
