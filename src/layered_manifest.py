from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import AutoEditorError


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ENTER_PRESETS = {
    "slide_left_fade", "slide_right_fade", "slide_up_fade",
    "slide_down_fade", "pop_in", "scale_in", "stamp_in",
    "paper_drop", "slight_rotate_in", "line_draw", "string_reveal",
    "highlight_flash",
}
TRANSITIONS = {
    "crossfade", "paper_swipe", "paper_slide", "paper_wipe", "collage_push",
    "push_left", "push_right", "zoom_fade", "none",
}
CAMERA_TYPES = {"none", "drift", "push_in", "push_out"}
ANCHORS = {
    "center", "top_left", "top_center", "top_right", "center_left",
    "center_right", "bottom_left", "bottom_center", "bottom_right",
}


@dataclass(frozen=True)
class LayerState:
    x: float
    y: float
    scale: float
    rotation: float
    opacity: float


@dataclass(frozen=True)
class LayerItem:
    id: str
    file: str
    state: LayerState
    z: int
    start: float
    duration: float
    enter: str
    anchor: str
    end_state: LayerState | None = None


@dataclass(frozen=True)
class CameraMotion:
    type: str = "none"
    start: float | None = None
    duration: float | None = None
    x: float = 0.0
    y: float = 0.0
    zoom: float = 1.0


@dataclass(frozen=True)
class SceneTransition:
    type: str = "none"
    duration: float = 0.0


@dataclass(frozen=True)
class LayeredSceneManifest:
    directory: Path
    width: int
    height: int
    background: str
    items: tuple[LayerItem, ...]
    camera: CameraMotion
    transition_out: SceneTransition

    @property
    def build_complete(self) -> float:
        return max((item.start + item.duration for item in self.items), default=0.0)


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AutoEditorError(f"Layered manifest: '{label}' phải là object.")
    return value


def _number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AutoEditorError(f"Layered manifest: '{label}' phải là số.")
    result = float(value)
    if not math.isfinite(result):
        raise AutoEditorError(f"Layered manifest: '{label}' phải là số hữu hạn.")
    if minimum is not None and result < minimum:
        raise AutoEditorError(f"Layered manifest: '{label}' phải >= {minimum}.")
    return result


def _integer(value: Any, label: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AutoEditorError(f"Layered manifest: '{label}' phải là số nguyên.")
    if value < minimum:
        raise AutoEditorError(f"Layered manifest: '{label}' phải >= {minimum}.")
    return value


def _safe_image(value: Any, label: str, directory: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AutoEditorError(f"Layered manifest: '{label}' phải là tên file ảnh.")
    filename = value.strip()
    path = Path(filename)
    if path.name != filename or path.is_absolute() or filename in {".", ".."}:
        raise AutoEditorError(f"Layered manifest: '{label}' phải là basename an toàn.")
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise AutoEditorError(f"Layered manifest: '{label}' có định dạng ảnh không hỗ trợ.")
    resolved = directory / filename
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise AutoEditorError(f"Layered manifest: không tìm thấy ảnh {resolved}.")
    try:
        from PIL import Image, UnidentifiedImageError
        with Image.open(resolved) as image:
            image.verify()
    except ImportError as exc:
        raise AutoEditorError("Thiếu Pillow. Hãy chạy SETUP.bat.") from exc
    except (OSError, UnidentifiedImageError) as exc:
        raise AutoEditorError(f"Layered manifest: ảnh corrupt {resolved}: {exc}") from exc
    return filename


def _state(raw: dict[str, Any], label: str, base: LayerState | None = None) -> LayerState:
    fallback = base or LayerState(0.0, 0.0, 1.0, 0.0, 1.0)
    state = LayerState(
        x=_number(raw.get("x", fallback.x), f"{label}.x"),
        y=_number(raw.get("y", fallback.y), f"{label}.y"),
        scale=_number(raw.get("scale", fallback.scale), f"{label}.scale", minimum=0.001),
        rotation=_number(raw.get("rotation", fallback.rotation), f"{label}.rotation"),
        opacity=_number(raw.get("opacity", fallback.opacity), f"{label}.opacity", minimum=0.0),
    )
    if state.opacity > 1.0:
        raise AutoEditorError(f"Layered manifest: '{label}.opacity' phải <= 1.")
    return state


def load_layered_manifest(
    directory: Path, *, expected_width: int | None = None, expected_height: int | None = None
) -> LayeredSceneManifest:
    manifest_path = directory / "manifest.json"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise AutoEditorError(f"Không tìm thấy layered manifest: {manifest_path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AutoEditorError(f"Không đọc được layered manifest {manifest_path}: {exc}") from exc
    root = _object(raw, "root")
    canvas = _object(root.get("canvas"), "canvas")
    width = _integer(canvas.get("width"), "canvas.width")
    height = _integer(canvas.get("height"), "canvas.height")
    if expected_width is not None and width != expected_width:
        raise AutoEditorError(f"Layered manifest canvas width phải là {expected_width}, nhận {width}.")
    if expected_height is not None and height != expected_height:
        raise AutoEditorError(f"Layered manifest canvas height phải là {expected_height}, nhận {height}.")
    background = _safe_image(root.get("background"), "background", directory)
    raw_items = root.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise AutoEditorError("Layered manifest: 'items' phải là danh sách không rỗng.")
    items: list[LayerItem] = []
    ids: set[str] = set()
    for index, value in enumerate(raw_items, 1):
        item = _object(value, f"items[{index}]")
        item_id = item.get("id", f"item_{index:02d}")
        if not isinstance(item_id, str) or not item_id.strip():
            raise AutoEditorError(f"Layered manifest: items[{index}].id phải là chuỗi.")
        item_id = item_id.strip()
        if item_id in ids:
            raise AutoEditorError(f"Layered manifest: item id bị trùng: {item_id}.")
        ids.add(item_id)
        filename = _safe_image(item.get("file", item.get("source")), f"items[{index}].file", directory)
        state = _state(item, f"items[{index}]")
        enter = item.get("enter", "scale_in")
        if enter not in ENTER_PRESETS:
            raise AutoEditorError(f"Layered manifest: enter không hỗ trợ: {enter!r}.")
        anchor = item.get("anchor", "center")
        if anchor not in ANCHORS:
            raise AutoEditorError(f"Layered manifest: anchor không hỗ trợ: {anchor!r}.")
        raw_end = item.get("end_state", item.get("end"))
        end_state = _state(_object(raw_end, f"items[{index}].end_state"), f"items[{index}].end_state", state) if raw_end is not None else None
        z = item.get("z", index)
        if isinstance(z, bool) or not isinstance(z, int):
            raise AutoEditorError(f"Layered manifest: items[{index}].z phải là số nguyên.")
        items.append(LayerItem(
            id=item_id, file=filename, state=state, z=z,
            start=_number(item.get("start", 0.0), f"items[{index}].start", minimum=0.0),
            duration=_number(item.get("duration", 0.5), f"items[{index}].duration", minimum=0.001),
            enter=enter, anchor=anchor, end_state=end_state,
        ))
    camera_raw = root.get("camera", {})
    camera_obj = _object(camera_raw, "camera")
    camera_type = camera_obj.get("type", "none")
    if camera_type not in CAMERA_TYPES:
        raise AutoEditorError(f"Layered manifest: camera.type không hỗ trợ: {camera_type!r}.")
    start_value = camera_obj.get("start")
    duration_value = camera_obj.get("duration")
    camera = CameraMotion(
        type=camera_type,
        start=_number(start_value, "camera.start", minimum=0.0) if start_value is not None else None,
        duration=_number(duration_value, "camera.duration", minimum=0.001) if duration_value is not None else None,
        x=_number(camera_obj.get("x", 0.0), "camera.x"),
        y=_number(camera_obj.get("y", 0.0), "camera.y"),
        zoom=_number(camera_obj.get("zoom", 1.0), "camera.zoom", minimum=0.001),
    )
    transition_obj = _object(root.get("transition_out", {}), "transition_out")
    transition_type = transition_obj.get("type", "none")
    if transition_type not in TRANSITIONS:
        raise AutoEditorError(f"Layered manifest: transition không hỗ trợ: {transition_type!r}.")
    transition_duration = _number(
        transition_obj.get("duration", 0.0 if transition_type == "none" else 0.5),
        "transition_out.duration", minimum=0.0,
    )
    if transition_type != "none" and transition_duration <= 0:
        raise AutoEditorError("Layered manifest: transition duration phải > 0.")
    return LayeredSceneManifest(
        directory=directory, width=width, height=height, background=background,
        items=tuple(sorted(items, key=lambda item: item.z)), camera=camera,
        transition_out=SceneTransition(transition_type, transition_duration),
    )


def smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def interpolate(start: float, end: float, progress: float) -> float:
    return start + (end - start) * smoothstep(progress)
