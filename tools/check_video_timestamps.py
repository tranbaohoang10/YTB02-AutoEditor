from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify monotonic constant-rate video timestamps")
    parser.add_argument("video", type=Path)
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--json", type=Path, dest="json_path")
    args = parser.parse_args(argv)
    result = subprocess.run([
        args.ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "frame=best_effort_timestamp_time", "-of", "csv=p=0",
        str(args.video),
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print(result.stderr[-2000:], file=sys.stderr)
        return 1
    timestamps = [
        float(line.rstrip(",")) for line in result.stdout.splitlines() if line.strip()
    ]
    expected_step = 1.0 / args.fps
    non_monotonic = sum(
        right <= left for left, right in zip(timestamps, timestamps[1:])
    )
    bad_steps = sum(
        abs((right - left) - expected_step) > 1e-5
        for left, right in zip(timestamps, timestamps[1:])
    )
    payload = {
        "source": str(args.video),
        "frame_count": len(timestamps),
        "first_pts": timestamps[0] if timestamps else None,
        "last_pts": timestamps[-1] if timestamps else None,
        "fps": args.fps,
        "non_monotonic_count": non_monotonic,
        "non_constant_step_count": bad_steps,
        "pass": bool(timestamps) and non_monotonic == 0 and bad_steps == 0,
    }
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
