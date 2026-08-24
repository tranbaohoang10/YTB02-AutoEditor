from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import AutoEditorError, Script


@dataclass(frozen=True)
class NarrationChunk:
    id: int
    scene_ids: tuple[int, ...]
    text: str
    output_path: Path


def build_narration_chunks(
    script: Script, audio_dir: Path, narration_mode: str,
    continuous_chunk_scenes: int,
) -> tuple[NarrationChunk, ...]:
    if narration_mode not in {"scene", "continuous"}:
        raise AutoEditorError(f"Narration mode không hỗ trợ: {narration_mode}")
    group_size = 1 if narration_mode == "scene" else continuous_chunk_scenes
    if group_size < 1:
        raise AutoEditorError("continuous_chunk_scenes phải >= 1.")
    chunks: list[NarrationChunk] = []
    for start in range(0, len(script.scenes), group_size):
        scenes = script.scenes[start:start + group_size]
        chunk_id = len(chunks) + 1
        stem = (
            f"scene_{scenes[0].id:03d}"
            if narration_mode == "scene"
            else f"chunk_{chunk_id:03d}"
        )
        chunks.append(
            NarrationChunk(
                id=chunk_id,
                scene_ids=tuple(scene.id for scene in scenes),
                text=" ".join(scene.text for scene in scenes),
                output_path=audio_dir / f"{stem}.wav",
            )
        )
    return tuple(chunks)


def generate_narration(
    script: Script,
    kokoro_python: Path,
    worker_path: Path,
    audio_dir: Path,
    work_dir: Path,
    sample_rate: int,
    narration_mode: str = "scene",
    continuous_chunk_scenes: int = 5,
) -> tuple[NarrationChunk, ...]:
    if not kokoro_python.is_file():
        raise AutoEditorError(f"Không tìm thấy Kokoro Python: {kokoro_python}")
    audio_dir.mkdir(parents=True, exist_ok=True)
    chunks = build_narration_chunks(
        script, audio_dir, narration_mode, continuous_chunk_scenes
    )
    manifest = work_dir / "tts_manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "id": chunk.id,
                    "scene_ids": list(chunk.scene_ids),
                    "text": chunk.text,
                    "output": chunk.output_path.name,
                }
                for chunk in chunks
            ],
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    command = [
        str(kokoro_python), str(worker_path),
        "--language", script.language,
        "--voice", script.voice,
        "--speed", str(script.speed),
        "--manifest", str(manifest),
        "--output-dir", str(audio_dir),
        "--sample-rate", str(sample_rate),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        raise AutoEditorError(f"Không chạy được Kokoro TTS: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise AutoEditorError(f"TTS generation failed: {detail[-2000:]}")
    for chunk in chunks:
        output = chunk.output_path
        if not output.is_file() or output.stat().st_size <= 44:
            raise AutoEditorError(
                f"TTS không tạo được WAV hợp lệ cho chunk {chunk.id}: {output}"
            )
    return chunks
