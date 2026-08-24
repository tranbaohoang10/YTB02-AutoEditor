from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.models import Scene, SceneAlignment, TimelineEntry, WordTiming
from src.transitions import schedule_pause_aware_transitions


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview pause-aware boundary decisions")
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--alignment-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    args = parser.parse_args()
    raw_script = json.loads(args.script.read_text(encoding="utf-8"))
    timeline: list[TimelineEntry] = []
    alignments: list[SceneAlignment] = []
    for raw_scene in raw_script["scenes"]:
        scene_id = int(raw_scene["id"])
        diagnostic = json.loads(
            (args.alignment_dir / f"scene_{scene_id:03d}.json").read_text(encoding="utf-8")
        )
        scene = Scene(scene_id, raw_scene.get("video"), str(raw_scene["text"]))
        start = float(diagnostic["timeline_start"])
        end = float(diagnostic["timeline_end"])
        timeline.append(TimelineEntry(scene, Path("voice.wav"), end - start, start, end))
        alignments.append(SceneAlignment(
            scene_id, str(raw_script["language"]),
            tuple(
                WordTiming(str(word["word"]), float(word["start"]), float(word["end"]))
                for word in diagnostic["words"]
            ),
        ))
    decisions = schedule_pause_aware_transitions(
        timeline, alignments, load_config(args.config).transitions
    )
    print(
        f"eligible={sum(item.eligible for item in decisions)} "
        f"visual={sum(item.has_visual for item in decisions)} "
        f"sfx={sum(item.has_sfx for item in decisions)}"
    )
    for item in decisions:
        sfx = item.sfx_path.name if item.sfx_path else "none"
        print(
            f"{item.from_scene:02d}->{item.to_scene:02d} "
            f"t={item.boundary_time:.3f}s pause={item.pause_seconds * 1000:.0f}ms "
            f"effect={item.effect} duration={item.visual_duration * 1000:.0f}ms "
            f"sfx={sfx} reason={item.reason}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
