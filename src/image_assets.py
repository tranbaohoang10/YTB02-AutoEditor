from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .image_prompt_builder import build_image_prompt
from .layered_manifest import load_layered_manifest
from .image_providers.base import ImageProvider
from .image_providers.gemini_api import GeminiApiImageProvider
from .image_providers.manual import ManualImageProvider
from .media_qc import validate_image
from .models import AutoEditorError, Scene, Script


def prompt_hash(prompt: str, provider: str, model: str) -> str:
    value = f"{provider}\0{model}\0{prompt}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class VisualAsset:
    kind: str
    path: Path


def create_image_provider(script: Script) -> ImageProvider:
    if script.visual.image_provider == "manual":
        return ManualImageProvider()
    return GeminiApiImageProvider(script.visual.image_model)


def _metadata_safe(payload: dict[str, object]) -> bool:
    serialized = json.dumps(payload, ensure_ascii=False).casefold()
    return not any(token in serialized for token in ("api_key", "gemini_api_key", "authorization"))


def resolve_visual_assets(
    script: Script,
    videos_dir: Path,
    images_dir: Path,
    generated_dir: Path,
    scenes_dir: Path | None = None,
    *,
    force: bool = False,
    provider: ImageProvider | None = None,
) -> dict[int, VisualAsset]:
    results: dict[int, VisualAsset] = {}
    active_provider = provider
    scene_root = scenes_dir or videos_dir.parent / "scenes"
    for scene in script.scenes:
        if scene.assets:
            path = scene_root / scene.assets
            load_layered_manifest(path)
            results[scene.id] = VisualAsset("layered", path)
            continue
        if scene.image:
            path = images_dir / scene.image
            validate_image(path)
            results[scene.id] = VisualAsset("image", path)
            continue
        if scene.video:
            path = videos_dir / scene.video
            if not path.is_file() or path.stat().st_size == 0:
                raise AutoEditorError(f"Scene {scene.id}: video rỗng hoặc không tồn tại: {path}")
            results[scene.id] = VisualAsset("video", path)
            continue
        if active_provider is None:
            active_provider = create_image_provider(script)
        prompt = build_image_prompt(script, scene)
        model = os.environ.get("GEMINI_IMAGE_MODEL") or script.visual.image_model
        digest = prompt_hash(prompt, active_provider.name, model)
        output = generated_dir / f"scene_{scene.id:03d}.png"
        sidecar = generated_dir / f"scene_{scene.id:03d}.json"
        if not force and output.is_file() and sidecar.is_file():
            try:
                cached = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cached = {}
            if cached.get("prompt_hash") == digest:
                validate_image(output)
                results[scene.id] = VisualAsset("image", output)
                continue
        metadata = {
            "scene_id": scene.id, "provider": active_provider.name, "model": model,
            "prompt": prompt, "prompt_hash": digest,
        }
        active_provider.generate(
            prompt, output, script.visual.aspect_ratio, script.visual.image_size, metadata
        )
        validate_image(output)
        payload = {
            **metadata,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "output_path": output.resolve().as_posix(),
        }
        if not _metadata_safe(payload):
            raise AutoEditorError("Cache metadata chứa tên credential không an toàn.")
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        results[scene.id] = VisualAsset("image", output)
    return results
