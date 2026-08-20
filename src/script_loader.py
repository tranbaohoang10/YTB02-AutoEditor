from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import AutoEditorError, Scene, Script


DEFAULT_VOICES = {"en": "am_eric", "vi": "hung_thinh"}
DEFAULT_SPEED = 1.08


def _require_scene(raw: Any, position: int) -> Scene:
    if not isinstance(raw, dict):
        raise AutoEditorError(f"Scene tại vị trí {position} phải là JSON object.")
    scene_id = raw.get("id")
    if not isinstance(scene_id, int) or isinstance(scene_id, bool):
        raise AutoEditorError(f"Scene tại vị trí {position}: 'id' phải là số nguyên.")
    video = raw.get("video")
    if not isinstance(video, str) or not video.strip():
        raise AutoEditorError(f"Scene {scene_id}: 'video' không được để trống.")
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        raise AutoEditorError(f"Scene {scene_id}: narration 'text' không được để trống.")
    if Path(video).name != video or Path(video).is_absolute():
        raise AutoEditorError(f"Scene {scene_id}: 'video' chỉ được là tên file, không phải đường dẫn.")
    return Scene(id=scene_id, video=video, text=text.strip())


def load_script(path: Path, videos_dir: Path, *, validate_videos: bool = True) -> Script:
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
    if validate_videos:
        for scene in scenes:
            video_path = videos_dir / scene.video
            if not video_path.is_file():
                raise AutoEditorError(f"Scene {scene.id}: không tìm thấy video {video_path}")
    return Script(
        title=title.strip(), language=language, voice=voice.strip(),
        speed=float(speed), scenes=tuple(scenes),
    )
