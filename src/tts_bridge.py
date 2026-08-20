from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .models import AutoEditorError, Script


def generate_narration(
    script: Script,
    kokoro_python: Path,
    worker_path: Path,
    audio_dir: Path,
    work_dir: Path,
    sample_rate: int,
) -> None:
    if not kokoro_python.is_file():
        raise AutoEditorError(f"Không tìm thấy Kokoro Python: {kokoro_python}")
    audio_dir.mkdir(parents=True, exist_ok=True)
    manifest = work_dir / "tts_manifest.json"
    manifest.write_text(
        json.dumps(
            [{"id": scene.id, "text": scene.text} for scene in script.scenes],
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
    for scene in script.scenes:
        output = audio_dir / f"scene_{scene.id:03d}.wav"
        if not output.is_file() or output.stat().st_size <= 44:
            raise AutoEditorError(f"TTS không tạo được WAV hợp lệ cho scene {scene.id}: {output}")
