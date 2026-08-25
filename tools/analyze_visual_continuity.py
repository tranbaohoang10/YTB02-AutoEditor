from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models import AutoEditorError  # noqa: E402
from src.visual_continuity import analyze_visual_continuity  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure static dead zones and transition motion at scene boundaries"
    )
    parser.add_argument("video", type=Path)
    parser.add_argument("--transitions", type=Path, required=True)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--json", type=Path, required=True, dest="json_path")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--motion-threshold", type=float, default=0.75)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = analyze_visual_continuity(
            args.video, args.transitions, ffmpeg=args.ffmpeg, fps=args.fps,
            motion_threshold=args.motion_threshold, freeze_path=args.freeze,
        )
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"Boundaries: {payload['scene_boundary_count']} | eligible >=250ms: "
            f"{payload['eligible_pause_count']}"
        )
        print(
            "Static dead zone eligible: avg "
            f"{payload['eligible_static_dead_zone_average_ms']:.1f}ms | max "
            f"{payload['eligible_static_dead_zone_max_ms']:.1f}ms | >200ms "
            f"{payload['eligible_over_200ms']}"
        )
        return 0
    except AutoEditorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
