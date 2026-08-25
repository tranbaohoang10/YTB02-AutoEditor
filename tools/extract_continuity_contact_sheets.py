from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models import AutoEditorError  # noqa: E402


def _select_boundaries(boundaries: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    short = [item for item in boundaries if item["available_narration_pause_ms"] < 250]
    medium = [
        item for item in boundaries
        if 250 <= item["available_narration_pause_ms"] < 380
    ]
    longest = sorted(
        boundaries, key=lambda item: item["available_narration_pause_ms"], reverse=True
    )
    chosen: list[tuple[str, dict[str, Any]]] = []
    selected: set[tuple[int, int]] = set()

    def add(category: str, candidates: Sequence[dict[str, Any]], limit: int) -> None:
        for item in candidates:
            key = (int(item["scene_from"]), int(item["scene_to"]))
            if key in selected:
                continue
            chosen.append((category, item))
            selected.add(key)
            if sum(1 for name, _ in chosen if name == category) >= limit:
                break

    add("short", short, 5)
    add(
        "medium",
        sorted(medium, key=lambda value: value["static_dead_zone_ms"], reverse=True),
        5,
    )
    add("longest", longest, 3)

    # Languages with slower delivery can have no short pauses at all. Fill the
    # visual QA sample from the remaining highest-risk boundaries rather than
    # failing because a pause class happens to be absent.
    remaining = sorted(
        boundaries,
        key=lambda item: (
            item["static_dead_zone_ms"], item["available_narration_pause_ms"]
        ),
        reverse=True,
    )
    for item in remaining:
        if len(chosen) >= min(13, len(boundaries)):
            break
        key = (int(item["scene_from"]), int(item["scene_to"]))
        if key not in selected:
            chosen.append(("representative", item))
            selected.add(key)
    return chosen


def _sample_times(item: dict[str, Any]) -> list[float]:
    pause_start = float(item["last_spoken_word_end"])
    pause_end = float(item["next_spoken_word_start"])
    transition_start = item.get("transition_start")
    transition_end = item.get("transition_end")
    if transition_start is None:
        transition_start = pause_start + (pause_end - pause_start) * 0.4
    if transition_end is None:
        transition_end = pause_start + (pause_end - pause_start) * 0.8
    return [
        max(0.0, pause_start - 1 / 30),
        pause_start,
        float(transition_start),
        (float(transition_start) + float(transition_end)) / 2,
        float(transition_end),
        pause_end + 1 / 30,
    ]


def extract_contact_sheets(
    video: Path, diagnostics: Path, output_dir: Path, *, ffmpeg: str = "ffmpeg",
) -> dict[str, Any]:
    payload = json.loads(diagnostics.read_text(encoding="utf-8-sig"))
    boundaries = list(payload["boundaries"])
    selected = _select_boundaries(boundaries)
    if len(selected) < min(13, len(boundaries)):
        raise AutoEditorError("Không chọn đủ boundary đại diện để QA.")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    for category, item in selected:
        times = _sample_times(item)
        destination = output_dir / (
            f"{category}_{int(item['scene_from']):02d}_{int(item['scene_to']):02d}.png"
        )
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
        for timestamp in times:
            command.extend(["-ss", f"{timestamp:.6f}", "-i", str(video)])
        labels: list[str] = []
        filters: list[str] = []
        for index in range(len(times)):
            label = f"frame{index}"
            labels.append(f"[{label}]")
            filters.append(
                f"[{index}:v:0]scale=320:180:force_original_aspect_ratio=decrease,"
                f"pad=320:180:(ow-iw)/2:(oh-ih)/2,setsar=1[{label}]"
            )
        filters.append(f"{''.join(labels)}hstack=inputs={len(labels)}[sheet]")
        command.extend([
            "-filter_complex", ";".join(filters), "-map", "[sheet]",
            "-frames:v", "1", "-update", "1", str(destination),
        ])
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            raise AutoEditorError(
                f"Không extract được contact sheet {destination.name}: {result.stderr[-2000:]}"
            )
        manifest.append({
            "category": category,
            "scene_from": item["scene_from"],
            "scene_to": item["scene_to"],
            "pause_ms": item["available_narration_pause_ms"],
            "effect": item["transition_type"],
            "static_dead_zone_ms": item["static_dead_zone_ms"],
            "sample_times": [round(value, 6) for value in times],
            "sheet": destination.name,
        })
    result_payload = {"source": str(video), "count": len(manifest), "sheets": manifest}
    (output_dir / "manifest.json").write_text(
        json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result_payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract continuity boundary contact sheets")
    parser.add_argument("video", type=Path)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args(argv)
    try:
        payload = extract_contact_sheets(
            args.video, args.diagnostics, args.output_dir, ffmpeg=args.ffmpeg
        )
        print(f"Contact sheets: {payload['count']} -> {args.output_dir}")
        return 0
    except (AutoEditorError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
