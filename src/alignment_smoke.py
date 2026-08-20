from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

from .alignment import WhisperXAlignmentEngine, validate_and_map_words
from .config import load_config
from .models import AutoEditorError
from .script_loader import load_script


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
    except (OSError, wave.Error) as exc:
        raise AutoEditorError(f"Không đọc được WAV smoke test {path}: {exc}") from exc
    if frame_rate <= 0 or frame_count <= 0:
        raise AutoEditorError(f"WAV smoke test rỗng hoặc không hợp lệ: {path}")
    return frame_count / frame_rate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run real WhisperX forced alignment without ASR or video rendering."
    )
    parser.add_argument("--language", choices=("en", "vi"), required=True)
    parser.add_argument("--scene-id", type=int, default=1)
    parser.add_argument("--wav", type=Path, help="WAV path; default work/audio/scene_XXX.wav")
    text_group = parser.add_mutually_exclusive_group()
    text_group.add_argument("--text", help="Canonical transcript text")
    text_group.add_argument("--text-file", type=Path, help="UTF-8 canonical transcript file")
    parser.add_argument(
        "--script", type=Path, default=PROJECT_ROOT / "input" / "script.json",
        help="Fallback source for canonical text when --text/--text-file is omitted",
    )
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config.json")
    return parser


def _canonical_text(args: argparse.Namespace) -> str:
    if args.text is not None:
        text = args.text
    elif args.text_file is not None:
        try:
            text = args.text_file.resolve().read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise AutoEditorError(f"Không đọc được --text-file: {exc}") from exc
    else:
        script = load_script(
            args.script.resolve(), PROJECT_ROOT / "input" / "videos", validate_videos=False
        )
        if script.language != args.language:
            raise AutoEditorError(
                f"Smoke language '{args.language}' không khớp script language '{script.language}'."
            )
        scene = next((item for item in script.scenes if item.id == args.scene_id), None)
        if scene is None:
            raise AutoEditorError(f"Không tìm thấy scene {args.scene_id} trong {args.script}.")
        text = scene.text
    if not text.strip():
        raise AutoEditorError("Canonical smoke transcript không được để trống.")
    return text.strip()


def run_smoke(args: argparse.Namespace) -> None:
    if args.scene_id < 1:
        raise AutoEditorError("--scene-id phải >= 1.")
    wav_path = (
        args.wav.resolve()
        if args.wav is not None
        else PROJECT_ROOT / "work" / "audio" / f"scene_{args.scene_id:03d}.wav"
    )
    if not wav_path.is_file():
        raise AutoEditorError(
            f"Không tìm thấy WAV: {wav_path}\n"
            "Hãy build narration trước hoặc truyền --wav PATH --text/--text-file."
        )
    text = _canonical_text(args)
    config = load_config(args.config.resolve())
    duration = wav_duration(wav_path)
    print(f"Loading WhisperX {args.language} alignment model on CPU...")
    engine = WhisperXAlignmentEngine(args.language, config.alignment)
    raw_words = engine.align(wav_path, text, duration)
    words = validate_and_map_words(
        text, raw_words, duration, config.alignment.duration_tolerance
    )
    print(f"Aligned {len(words)} canonical words from {wav_path}")
    print("START      END        WORD")
    for word in words:
        print(f"{word.start:9.3f}  {word.end:9.3f}  {word.word}")
    print("ALIGNMENT SMOKE PASS - no missing or extra canonical words.")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    args = _parser().parse_args(argv)
    try:
        run_smoke(args)
        return 0
    except AutoEditorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Đã hủy smoke test.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
