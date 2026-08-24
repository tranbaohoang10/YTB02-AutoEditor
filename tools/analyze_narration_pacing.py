from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models import AutoEditorError  # noqa: E402
from src.narration import (  # noqa: E402
    detect_pause_regions,
    pause_statistics,
    read_pcm16_mono,
)


def _extract_wav(media_path: Path, ffmpeg: str, destination: Path) -> Path:
    if media_path.suffix.lower() == ".wav":
        return media_path
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(media_path), "-map", "0:a:0", "-ar", "48000", "-ac", "1",
        "-c:a", "pcm_s16le", str(destination),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except OSError as exc:
        raise AutoEditorError(f"Không chạy được FFmpeg: {exc}") from exc
    if result.returncode != 0:
        raise AutoEditorError(
            f"FFmpeg không trích được audio: {(result.stderr or result.stdout)[-2000:]}"
        )
    return destination


def _alignment_gaps(alignment_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    paths = sorted(alignment_dir.glob("scene_*.json"))
    rows = [json.loads(path.read_text(encoding="utf-8-sig")) for path in paths]
    internal: list[dict[str, Any]] = []
    boundaries: list[dict[str, Any]] = []
    inferred_cursor = 0.0
    scene_data: list[tuple[dict[str, Any], float, float]] = []
    for row in rows:
        start = float(row.get("timeline_start", inferred_cursor))
        duration = float(row["audio_duration"])
        end = float(row.get("timeline_end", start + duration))
        scene_data.append((row, start, end))
        inferred_cursor = end
        words = row.get("words", [])
        for previous, current in zip(words, words[1:]):
            gap = float(current["start"]) - float(previous["end"])
            if gap < 0:
                continue
            previous_word = str(previous["word"])
            classification = (
                "intentional_punctuation"
                if re.search(r"[,.;:!?][\"']?$", previous_word)
                else "internal_sentence"
            )
            internal.append(
                {
                    "scene_id": int(row["scene_id"]),
                    "start": round(start + float(previous["end"]), 6),
                    "end": round(start + float(current["start"]), 6),
                    "duration": round(gap, 6),
                    "classification": classification,
                    "previous_word": previous_word,
                    "next_word": str(current["word"]),
                }
            )
    for (row, start, _), (next_row, next_start, _) in zip(scene_data, scene_data[1:]):
        words = row.get("words", [])
        next_words = next_row.get("words", [])
        if not words or not next_words:
            continue
        last_end = start + float(words[-1]["end"])
        first_start = next_start + float(next_words[0]["start"])
        boundaries.append(
            {
                "after_scene": int(row["scene_id"]),
                "before_scene": int(next_row["scene_id"]),
                "start": round(last_end, 6),
                "end": round(first_start, 6),
                "duration": round(max(0.0, first_start - last_end), 6),
                "classification": "scene_boundary",
            }
        )
    return internal, boundaries


def analyze(
    media_path: Path, *, threshold_db: float = -35.0, minimum_ms: int = 120,
    ffmpeg: str = "ffmpeg", alignment_dir: Path | None = None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ytb02-pacing-") as directory:
        wav_path = _extract_wav(media_path, ffmpeg, Path(directory) / "audio.wav")
        parameters, samples = read_pcm16_mono(wav_path)
    duration = len(samples) / parameters.framerate
    regions = detect_pause_regions(
        samples, parameters.framerate, threshold_db, minimum_ms
    )
    segments = [
        {
            "start": round(region.start_frame / parameters.framerate, 6),
            "end": round(region.end_frame / parameters.framerate, 6),
            "duration": round(region.duration_ms / 1000.0, 6),
            "classification": "unclassified",
        }
        for region in regions
    ]
    internal: list[dict[str, Any]] = []
    boundaries: list[dict[str, Any]] = []
    if alignment_dir is not None:
        internal, boundaries = _alignment_gaps(alignment_dir)
        for segment in segments:
            if any(
                max(segment["start"] - 0.03, boundary["start"])
                < min(segment["end"] + 0.03, boundary["end"])
                for boundary in boundaries
            ):
                segment["classification"] = "scene_boundary"
            elif any(
                max(segment["start"], pause["start"])
                < min(segment["end"], pause["end"])
                for pause in internal
            ):
                segment["classification"] = "internal_sentence"
    pause_durations = [float(segment["duration"]) for segment in segments]
    silence_duration = sum(pause_durations)
    aligned = [*internal, *boundaries]
    aligned_measured = [item for item in aligned if float(item["duration"]) >= minimum_ms / 1000.0]
    return {
        "source": str(media_path),
        "detector": {
            "type": "PCM window RMS with peak phoneme guard",
            "threshold_db": threshold_db,
            "minimum_silence_ms": minimum_ms,
            "window_ms": 10,
        },
        "total_duration": round(duration, 6),
        "speech_duration": round(duration - silence_duration, 6),
        "silence_duration": round(silence_duration, 6),
        "silence_ratio": round(silence_duration / duration, 6) if duration else 0.0,
        "silence_count": len(segments),
        "pause_buckets": {
            "short_under_180ms": sum(value < 0.18 for value in pause_durations),
            "medium_180_300ms": sum(0.18 <= value < 0.3 for value in pause_durations),
            "long_300_500ms": sum(0.3 <= value < 0.5 for value in pause_durations),
            "very_long_over_500ms": sum(value >= 0.5 for value in pause_durations),
        },
        "pcm_pause_summary": pause_statistics(pause_durations),
        "aligned_gap_summary": pause_statistics(
            [float(item["duration"]) for item in aligned_measured]
        ),
        "scene_boundary_summary": pause_statistics(
            [float(item["duration"]) for item in boundaries]
        ),
        "internal_gap_summary": pause_statistics(
            [float(item["duration"]) for item in internal if float(item["duration"]) >= minimum_ms / 1000.0]
        ),
        "scene_boundaries": boundaries,
        "internal_pauses": [
            item for item in internal if float(item["duration"]) >= minimum_ms / 1000.0
        ],
        "pcm_silences": segments,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze narration pause pacing")
    parser.add_argument("media", type=Path, help="Voice WAV or final video")
    parser.add_argument("--json", type=Path, dest="json_path")
    parser.add_argument("--alignment-dir", type=Path)
    parser.add_argument("--threshold-db", type=float, default=-35.0)
    parser.add_argument("--minimum-ms", type=int, default=120)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = analyze(
            args.media, threshold_db=args.threshold_db, minimum_ms=args.minimum_ms,
            ffmpeg=args.ffmpeg, alignment_dir=args.alignment_dir,
        )
        if args.json_path:
            args.json_path.parent.mkdir(parents=True, exist_ok=True)
            args.json_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        summary = result["pcm_pause_summary"]
        boundaries = result["scene_boundary_summary"]
        print(f"Source: {result['source']}")
        print(
            f"Duration {result['total_duration']:.3f}s | speech "
            f"{result['speech_duration']:.3f}s | detected silence "
            f"{result['silence_duration']:.3f}s ({result['silence_ratio']:.1%})"
        )
        print(
            f"PCM pauses: {summary['count']} | avg {summary['average']:.3f}s | "
            f"p90 {summary['p90']:.3f}s | p95 {summary['p95']:.3f}s | "
            f"max {summary['maximum']:.3f}s | >300ms {summary['over_300ms']}"
        )
        if args.alignment_dir:
            print(
                f"Scene boundaries: {boundaries['count']} | avg "
                f"{boundaries['average']:.3f}s | p95 {boundaries['p95']:.3f}s | "
                f"max {boundaries['maximum']:.3f}s"
            )
        return 0
    except AutoEditorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
