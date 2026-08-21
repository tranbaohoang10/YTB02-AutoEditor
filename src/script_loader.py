from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import AutoEditorError, Scene, Script, VisualSettings


DEFAULT_VOICES = {"en": "am_eric", "vi": "hung_thinh"}
DEFAULT_SPEED = 1.08
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MOTION_TYPES = {
    "slow_push_in", "slow_pull_out", "pan_left", "pan_right",
    "pan_up", "pan_down", "drift_subtle", "static", "auto",
}


def _optional_text(raw: dict[str, Any], name: str) -> str | None:
    value = raw.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise AutoEditorError(f"'{name}' phải là chuỗi.")
    return value.strip() or None


def _safe_filename(value: str, scene_id: int, field: str) -> str:
    path = Path(value)
    if path.name != value or path.is_absolute() or value in {".", ".."}:
        raise AutoEditorError(
            f"Scene {scene_id}: '{field}' chỉ được là tên file an toàn, không phải đường dẫn."
        )
    return value


def _require_scene(raw: Any, position: int) -> Scene:
    if not isinstance(raw, dict):
        raise AutoEditorError(f"Scene tại vị trí {position} phải là JSON object.")
    scene_id = raw.get("id")
    if not isinstance(scene_id, int) or isinstance(scene_id, bool):
        raise AutoEditorError(f"Scene tại vị trí {position}: 'id' phải là số nguyên.")
    video = _optional_text(raw, "video")
    image = _optional_text(raw, "image")
    visual_hint = _optional_text(raw, "visual_hint")
    image_prompt = _optional_text(raw, "image_prompt")
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        raise AutoEditorError(f"Scene {scene_id}: narration 'text' không được để trống.")
    if video:
        video = _safe_filename(video, scene_id, "video")
    if image:
        image = _safe_filename(image, scene_id, "image")
        if Path(image).suffix.lower() not in IMAGE_EXTENSIONS:
            raise AutoEditorError(
                f"Scene {scene_id}: định dạng ảnh không hỗ trợ: {Path(image).suffix or '(thiếu extension)'}."
            )
    if not any((video, image, image_prompt, visual_hint)):
        raise AutoEditorError(
            f"Scene {scene_id}: cần ít nhất video, image, image_prompt hoặc visual_hint."
        )
    motion = raw.get("motion", {})
    if motion is None:
        motion = {}
    if not isinstance(motion, dict):
        raise AutoEditorError(f"Scene {scene_id}: 'motion' phải là object.")
    motion_type = motion.get("type", "auto")
    if motion_type not in MOTION_TYPES:
        raise AutoEditorError(
            f"Scene {scene_id}: motion.type không hỗ trợ: {motion_type!r}."
        )
    return Scene(
        id=scene_id, video=video, text=text.strip(), image=image,
        visual_hint=visual_hint, image_prompt=image_prompt, motion_type=motion_type,
    )


def _visual_settings(raw: Any) -> VisualSettings:
    if raw is None:
        return VisualSettings()
    if not isinstance(raw, dict):
        raise AutoEditorError("'visual' phải là JSON object.")
    provider = str(raw.get("image_provider", "manual"))
    if provider not in {"manual", "gemini_api"}:
        raise AutoEditorError("visual.image_provider chỉ hỗ trợ 'manual' hoặc 'gemini_api'.")
    motion_mode = str(raw.get("motion_mode", "local"))
    if motion_mode not in {"local", "ai", "auto"}:
        raise AutoEditorError("visual.motion_mode chỉ hỗ trợ local, ai hoặc auto.")
    fallback = raw.get("ai_fallback_local", False)
    if not isinstance(fallback, bool):
        raise AutoEditorError("visual.ai_fallback_local phải là boolean.")
    motion_provider = _optional_text(raw, "motion_provider")
    if motion_provider not in {None, "gemini_image_to_video"}:
        raise AutoEditorError(
            "visual.motion_provider chỉ hỗ trợ 'gemini_image_to_video' hoặc null."
        )
    return VisualSettings(
        image_provider=provider,
        image_model=str(raw.get("image_model", "gemini-3.1-flash-image")),
        style_preset=str(raw.get("style_preset", "newsprint-editorial")),
        aspect_ratio=str(raw.get("aspect_ratio", "16:9")),
        image_size=str(raw.get("image_size", "2K")),
        motion_mode=motion_mode,
        motion_provider=motion_provider,
        motion_model=str(raw.get("motion_model", "veo-3.1-generate-preview")),
        ai_fallback_local=fallback,
    )


def load_script(
    path: Path,
    videos_dir: Path,
    images_dir: Path | None = None,
    *,
    validate_videos: bool = True,
) -> Script:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise AutoEditorError(
            f"Không tìm thấy script: {path}. Hãy copy input/script.example.json thành input/script.json."
        ) from exc
    except json.JSONDecodeError as exc:
        raise AutoEditorError(
            f"Script JSON không hợp lệ tại dòng {exc.lineno}, cột {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise AutoEditorError(f"Không đọc được script: {exc}") from exc
    if not isinstance(raw, dict):
        raise AutoEditorError("Script JSON phải là một object.")
    language = raw.get("language")
    if language not in DEFAULT_VOICES:
        raise AutoEditorError("language chỉ hỗ trợ 'en' hoặc 'vi'.")
    title = raw.get("title", "")
    if not isinstance(title, str):
        raise AutoEditorError("'title' phải là chuỗi.")
    voice = raw.get("voice") or DEFAULT_VOICES[language]
    if not isinstance(voice, str) or not voice.strip():
        raise AutoEditorError("'voice' không được để trống.")
    speed = raw.get("speed", DEFAULT_SPEED)
    if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not 0.25 <= float(speed) <= 4.0:
        raise AutoEditorError("'speed' phải là số trong khoảng 0.25..4.0.")
    raw_scenes = raw.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise AutoEditorError("'scenes' phải là danh sách có ít nhất một scene.")
    scenes = [_require_scene(item, i) for i, item in enumerate(raw_scenes, 1)]
    ids = [scene.id for scene in scenes]
    if len(set(ids)) != len(ids):
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        raise AutoEditorError(f"Scene id bị trùng: {duplicates}.")
    expected = list(range(1, len(scenes) + 1))
    if sorted(ids) != expected:
        raise AutoEditorError(f"Scene id phải liên tục từ 1. Nhận được {sorted(ids)}, cần {expected}.")
    scenes.sort(key=lambda scene: scene.id)
    visual = _visual_settings(raw.get("visual"))
    image_root = images_dir or videos_dir.parent / "images"
    if validate_videos:
        for scene in scenes:
            if scene.image:
                image_path = image_root / scene.image
                if not image_path.is_file():
                    raise AutoEditorError(f"Scene {scene.id}: không tìm thấy ảnh {image_path}")
            elif scene.video:
                video_path = videos_dir / scene.video
                if not video_path.is_file():
                    raise AutoEditorError(f"Scene {scene.id}: không tìm thấy video {video_path}")
            elif visual.image_provider == "manual":
                raise AutoEditorError(
                    f"Scene {scene.id}: manual image provider cần file image có sẵn."
                )
    return Script(
        title=title.strip(), language=language, voice=voice.strip(),
        speed=float(speed), scenes=tuple(scenes), visual=visual,
    )
