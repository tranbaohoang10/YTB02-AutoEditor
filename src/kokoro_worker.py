from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable


def _as_array(value: Any, np: Any) -> Any:
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value, dtype=np.float32).reshape(-1)


def _english_generator(engine: Any, text: str, voice: str, speed: float) -> Iterable[Any]:
    return engine(text, voice=voice, speed=speed)


def _vietnamese_audio(engine: Any, text: str, voice: str, speed: float) -> Any:
    # Current kokoro-vietnamese releases expose generate(); accept common compatible APIs.
    for name in ("generate", "synthesize", "tts"):
        method = getattr(engine, name, None)
        if method:
            try:
                return method(text, voice=voice, speed=speed)
            except TypeError:
                try:
                    return method(text, speed=speed)
                except TypeError:
                    return method(text)
    if callable(engine):
        try:
            return engine(text, voice=voice, speed=speed)
        except TypeError:
            return engine(text)
    raise RuntimeError("Không tìm thấy API generate/synthesize/tts của KokoroVietnamese.")


def _extract_audio(value: Any, np: Any) -> Any:
    audio_attribute = getattr(value, "audio", None)
    if audio_attribute is not None:
        value = audio_attribute
    if isinstance(value, tuple):
        value = value[-1]
    if isinstance(value, dict):
        value = value.get("audio", value.get("waveform"))
    return _as_array(value, np)


def _extract_vietnamese_audio(value: Any, np: Any) -> Any:
    # KokoroVietnamese.synthesize() returns (audio, phoneme_debug_text).
    if isinstance(value, tuple):
        value = value[0]
    if isinstance(value, dict):
        value = value.get("audio", value.get("waveform"))
    return _as_array(value, np)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=("en", "vi"), required=True)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--speed", type=float, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sample-rate", type=int, default=24000)
    args = parser.parse_args()
    try:
        import numpy as np
        import soundfile as sf

        scenes = json.loads(args.manifest.read_text(encoding="utf-8"))
        args.output_dir.mkdir(parents=True, exist_ok=True)
        if args.language == "en":
            from kokoro import KPipeline

            engine = KPipeline(lang_code="a", device="cpu")
        else:
            from kokoro_vietnamese import KokoroVietnamese

            try:
                engine = KokoroVietnamese(device="cpu", voice=args.voice)
            except TypeError:
                engine = KokoroVietnamese(device="cpu")

        for scene in scenes:
            if args.language == "en":
                pieces = [
                    _extract_audio(item, np)
                    for item in _english_generator(engine, scene["text"], args.voice, args.speed)
                ]
                audio = np.concatenate([item for item in pieces if item.size]) if pieces else np.array([])
            else:
                audio = _extract_vietnamese_audio(
                    _vietnamese_audio(engine, scene["text"], args.voice, args.speed), np
                )
            if audio.size == 0:
                raise RuntimeError(f"Kokoro trả về audio rỗng cho scene {scene['id']}.")
            output_name = str(scene.get("output", f"scene_{int(scene['id']):03d}.wav"))
            if Path(output_name).name != output_name or Path(output_name).suffix.lower() != ".wav":
                raise RuntimeError(f"Tên output TTS không an toàn: {output_name!r}")
            sf.write(args.output_dir / output_name, audio, args.sample_rate)
            print(
                f"chunk {int(scene['id']):03d}: {audio.size / args.sample_rate:.3f}s",
                flush=True,
            )
        return 0
    except Exception as exc:
        print(f"Kokoro worker error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
