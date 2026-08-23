"""Verify artifacts from the opt-in real manual-image E2E build."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.models import Scene, SceneAlignment, TimelineEntry, WordTiming
from src.pipeline import latest_final_video_path
from src.subtitles import create_rolling_cues, format_ass_timestamp, format_srt_timestamp


def _probe(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe not found")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt", "-of", "json", str(path)],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(result.stdout)


def main() -> int:
    script_data = json.loads((ROOT / "work/image-first-smoke-script.json").read_text(encoding="utf-8"))
    raw_scene = script_data["scenes"][0]
    scene = Scene(raw_scene["id"], None, raw_scene["text"], image=raw_scene["image"])
    wav_path = ROOT / "work/audio/scene_001.wav"
    with wave.open(str(wav_path), "rb") as wav:
        duration = wav.getnframes() / wav.getframerate()
    diagnostics = json.loads((ROOT / "work/alignment/scene_001.json").read_text(encoding="utf-8"))
    assert diagnostics["status"] == "ok"
    assert diagnostics["canonical_text"] == scene.text
    assert diagnostics["aligned_count"] == diagnostics["canonical_count"]
    words = tuple(WordTiming(item["word"], item["start"], item["end"]) for item in diagnostics["words"])
    alignment = SceneAlignment(1, "en", words)
    timeline = (TimelineEntry(scene, wav_path, duration, 0.0, duration),)
    cues = create_rolling_cues((alignment,), timeline, load_config(ROOT / "config.json").subtitles)
    for cue in cues:
        visible = cue.text.replace("\n", " ")
        count = len(visible.split())
        matches = [words[start:start + count] for start in range(len(words) - count + 1) if " ".join(word.word for word in words[start:start + count]) == visible]
        assert matches and any(all(word.start <= cue.start + 1e-9 for word in match) for match in matches)
    srt = (ROOT / "output/subtitles.srt").read_text(encoding="utf-8")
    ass = (ROOT / "output/subtitles.ass").read_text(encoding="utf-8-sig")
    for cue in cues:
        assert f"{format_srt_timestamp(cue.start)} --> {format_srt_timestamp(cue.end)}" in srt
        assert f"Dialogue: 0,{format_ass_timestamp(cue.start)},{format_ass_timestamp(cue.end)}," in ass
    assert ",0,2,60,60,70,1" in ass
    final = _probe(latest_final_video_path(ROOT / "output"))
    motion = _probe(ROOT / "work/motion/scene_001.mp4")
    video = next(stream for stream in final["streams"] if stream["codec_type"] == "video")
    audio = next(stream for stream in final["streams"] if stream["codec_type"] == "audio")
    assert (video["width"], video["height"], video["r_frame_rate"]) == (1920, 1080, "30/1")
    assert video["codec_name"] == "h264" and video["pix_fmt"] == "yuv420p"
    assert audio["codec_name"] == "aac"
    assert abs(float(final["format"]["duration"]) - duration) <= 1 / 30 + 0.01
    assert abs(float(motion["format"]["duration"]) - duration) <= 1 / 30 + 0.01
    print("REAL MANUAL-IMAGE E2E: PASS")
    print("KOKORO ENGLISH + WHISPERX ALIGNMENT: PASS")
    print("REAL NO-FUTURE-WORD / SRT CEIL / ASS CEIL: PASS")
    print(json.dumps({
        "resolution": f"{video['width']}x{video['height']}",
        "fps": video["r_frame_rate"], "video_codec": video["codec_name"],
        "pixel_format": video["pix_fmt"], "audio_codec": audio["codec_name"],
        "duration": float(final["format"]["duration"]),
        "audio_master_duration": duration,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
