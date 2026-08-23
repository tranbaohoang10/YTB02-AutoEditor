"""Verify artifacts from the opt-in real layered-collage E2E build."""

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


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as stream:
        return stream.getnframes() / stream.getframerate()


def probe(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe not found")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt,color_range,color_space",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(result.stdout)


def main() -> int:
    raw = json.loads((ROOT / "work/layered-e2e-script.json").read_text(encoding="utf-8"))
    scenes = tuple(
        Scene(item["id"], None, item["text"], assets=item["assets"])
        for item in raw["scenes"]
    )
    config = load_config(ROOT / "config.json")
    gap = config.audio.gap_ms / 1000.0
    cursor = 0.0
    timeline: list[TimelineEntry] = []
    alignments: list[SceneAlignment] = []
    for index, scene in enumerate(scenes):
        wav = ROOT / f"work/audio/scene_{scene.id:03d}.wav"
        duration = wav_duration(wav)
        timeline.append(TimelineEntry(scene, wav, duration, cursor, cursor + duration))
        diagnostics = json.loads(
            (ROOT / f"work/alignment/scene_{scene.id:03d}.json").read_text(encoding="utf-8")
        )
        assert diagnostics["status"] == "ok"
        assert diagnostics["canonical_text"] == scene.text
        assert diagnostics["aligned_count"] == diagnostics["canonical_count"]
        words = tuple(
            WordTiming(item["word"], item["start"], item["end"])
            for item in diagnostics["words"]
        )
        alignments.append(SceneAlignment(scene.id, raw["language"], words))
        prepared = probe(ROOT / f"work/scenes/scene_{scene.id:03d}.mp4")
        stream = prepared["streams"][0]
        assert stream["codec_name"] == "h264"
        assert (stream["width"], stream["height"]) == (1920, 1080)
        assert stream["r_frame_rate"] == "30/1"
        assert stream["pix_fmt"] == "yuv420p"
        assert stream["color_range"] == "tv"
        expected_visual = duration + (gap if index < len(scenes) - 1 else 0.0)
        assert abs(float(prepared["format"]["duration"]) - expected_visual) <= 1 / 30 + 0.02
        cursor += duration + (gap if index < len(scenes) - 1 else 0.0)

    cues = create_rolling_cues(tuple(alignments), tuple(timeline), config.subtitles)
    all_words = [
        WordTiming(word.word, word.start + entry.start, word.end + entry.start)
        for entry, alignment in zip(timeline, alignments)
        for word in alignment.words
    ]
    for cue in cues:
        visible = cue.text.replace("\n", " ")
        count = len(visible.split())
        matches = [
            all_words[start:start + count]
            for start in range(len(all_words) - count + 1)
            if " ".join(word.word for word in all_words[start:start + count]) == visible
        ]
        assert matches and any(
            all(word.start <= cue.start + 1e-9 for word in match) for match in matches
        )
    srt = (ROOT / "output/subtitles.srt").read_text(encoding="utf-8")
    ass = (ROOT / "output/subtitles.ass").read_text(encoding="utf-8-sig")
    for cue in cues:
        assert f"{format_srt_timestamp(cue.start)} --> {format_srt_timestamp(cue.end)}" in srt
        assert f"Dialogue: 0,{format_ass_timestamp(cue.start)},{format_ass_timestamp(cue.end)}," in ass

    final = probe(latest_final_video_path(ROOT / "output"))
    video = next(stream for stream in final["streams"] if stream["codec_type"] == "video")
    audio = next(stream for stream in final["streams"] if stream["codec_type"] == "audio")
    assert video["codec_name"] == "h264"
    assert (video["width"], video["height"]) == (1920, 1080)
    assert video["r_frame_rate"] == "30/1"
    assert video["pix_fmt"] == "yuv420p"
    assert video["color_range"] == "tv"
    assert video["color_space"] == "bt709"
    assert audio["codec_name"] == "aac"
    assert abs(float(final["format"]["duration"]) - cursor) <= 1 / 30 + 0.02
    print("REAL TWO-SCENE LAYERED E2E: PASS")
    print("KOKORO + WHISPERX + REAL NO-FUTURE-WORD: PASS")
    print(json.dumps({
        "scenes": len(scenes),
        "canonical_words": sum(len(item.words) for item in alignments),
        "duration": float(final["format"]["duration"]),
        "audio_master_duration": cursor,
        "resolution": f"{video['width']}x{video['height']}",
        "fps": video["r_frame_rate"],
        "video_codec": video["codec_name"],
        "pixel_format": video["pix_fmt"],
        "color_range": video["color_range"],
        "color_space": video["color_space"],
        "audio_codec": audio["codec_name"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
