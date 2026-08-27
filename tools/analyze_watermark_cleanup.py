from __future__ import annotations

import argparse
import io
import json
import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.ffmpeg_utils import probe_duration
from src.models import AutoEditorError
from src.visual_quality import analyze_video_profile


def _corner_frame(path: Path, timestamp: float, ffmpeg: str) -> Image.Image:
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{timestamp:.6f}",
        "-i", str(path), "-frames:v", "1", "-vf",
        "crop=480:300:iw-480:ih-300", "-f", "image2pipe", "-vcodec", "png", "pipe:1",
    ]
    result = subprocess.run(command, capture_output=True)
    if result.returncode != 0 or not result.stdout:
        detail = result.stderr.decode("utf-8", errors="replace")
        raise AutoEditorError(f"Không trích được corner frame {path.name}: {detail[-1500:]}")
    return Image.open(io.BytesIO(result.stdout)).convert("RGB")


def _contact_sheet(
    paths: list[Path], timestamp: float, destination: Path,
    ffmpeg: str, ffprobe: str, label: str,
) -> None:
    columns = 5
    rows = math.ceil(len(paths) / columns)
    sheet = Image.new("RGB", (columns * 480, rows * 300), "black")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=24)
    for index, path in enumerate(paths):
        duration = probe_duration(path, ffprobe)
        selected = min(timestamp, max(0.0, duration - 0.1))
        frame = _corner_frame(path, selected, ffmpeg)
        x = (index % columns) * 480
        y = (index // columns) * 300
        sheet.paste(frame, (x, y))
        text = f"{label} {path.stem} t={selected:.1f}s"
        draw.text((x + 10, y + 8), text, font=font, fill="yellow", stroke_width=2, stroke_fill="black")
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create deterministic source/prepared corner watermark QA sheets"
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--prepared-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--timestamps", type=float, nargs="+", default=(0.5, 2.0, 3.5))
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    config = load_config(args.config)
    sources = sorted(args.source_dir.glob("scene_*.mp4"))
    prepared = sorted(args.prepared_dir.glob("scene_*.mp4"))
    if not sources:
        raise AutoEditorError("Không tìm thấy source scene_*.mp4.")
    if len(prepared) != len(sources):
        raise AutoEditorError(
            f"Số prepared scene ({len(prepared)}) không khớp source ({len(sources)})."
        )

    sheets: list[str] = []
    for timestamp in args.timestamps:
        suffix = str(timestamp).replace(".", "p")
        for label, paths in (("source", sources), ("prepared", prepared)):
            destination = args.output_dir / f"{label}_corner_t{suffix}.png"
            _contact_sheet(
                paths, timestamp, destination, config.ffmpeg, config.ffprobe, label
            )
            sheets.append(destination.resolve().as_posix())

    source_scores: list[float] = []
    prepared_scores: list[float] = []
    for scene_id, (source, cleaned) in enumerate(zip(sources, prepared), 1):
        source_scores.append(analyze_video_profile(
            scene_id, source, probe_duration(source, config.ffprobe), config
        ).flow_logo_score)
        prepared_scores.append(analyze_video_profile(
            scene_id, cleaned, probe_duration(cleaned, config.ffprobe), config
        ).flow_logo_score)

    payload = {
        "source_scene_count": len(sources),
        "prepared_scene_count": len(prepared),
        "cleanup_enabled": config.source_cleanup.enabled,
        "cleanup_strategy": config.source_cleanup.strategy,
        "cleanup_target": config.source_cleanup.target,
        "final_watermark_composite_asset": str(config.watermark.logo_file),
        "final_watermark_position": config.watermark.position,
        "source_logo_score_range": [round(min(source_scores), 6), round(max(source_scores), 6)],
        "prepared_logo_score_range": [
            round(min(prepared_scores), 6), round(max(prepared_scores), 6)
        ],
        "contact_sheets": sheets,
        "structural_checks": {
            "all_sources_have_prepared_output": len(sources) == len(prepared),
            "cleanup_happens_before_final": config.source_cleanup.enabled,
            "configured_final_branding_is_single_composite_asset": (
                config.watermark.enabled
                and config.watermark.logo_file.is_file()
                and config.watermark.position == "bottom_right"
            ),
        },
        "manual_visual_gate": (
            "Inspect every source/prepared contact-sheet pair: no recognizable Gemini/Flow "
            "sparkle may remain; cleanup must not flicker or remove the main focal point."
        ),
    }
    destination = args.json or args.output_dir / "watermark_cleanup.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
