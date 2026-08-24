"""Verify artifacts from the opt-in real 30-scene Flow-video build."""

from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.ffmpeg_utils import probe_audio_duration
from src.models import SceneAlignment, TimelineEntry, WordTiming
from src.pipeline import latest_final_video_path
from src.script_loader import load_script
from src.subtitles import create_rolling_cues, format_ass_timestamp, format_srt_timestamp
from tools.analyze_narration_pacing import analyze


def _wav_samples(path: Path) -> tuple[int, int, tuple[int, ...]]:
    with wave.open(str(path), "rb") as source:
        sample_rate = source.getframerate()
        channels = source.getnchannels()
        frames = source.readframes(source.getnframes())
    return sample_rate, channels, struct.unpack(f"<{len(frames) // 2}h", frames)


def _wav_duration(path: Path) -> float:
    sample_rate, channels, samples = _wav_samples(path)
    return len(samples) / channels / sample_rate


def _wav_rms(path: Path) -> float:
    _, _, samples = _wav_samples(path)
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def _edge_silence(path: Path, threshold_db: float = -45.0) -> tuple[float, float]:
    sample_rate, channels, interleaved = _wav_samples(path)
    samples = interleaved[::channels]
    window = max(1, sample_rate // 100)
    threshold = 32767.0 * 10 ** (threshold_db / 20.0)
    active: list[int] = []
    for start in range(0, len(samples), window):
        chunk = samples[start:start + window]
        rms = math.sqrt(sum(value * value for value in chunk) / max(1, len(chunk)))
        if rms > threshold:
            active.append(start)
    assert active, f"WAV chỉ có silence: {path}"
    leading = active[0] / sample_rate
    trailing = max(0, len(samples) - active[-1] - window) / sample_rate
    return leading, trailing


def _probe_final(path: Path, ffprobe: str) -> dict:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "format=duration,size:stream=codec_type,codec_name,sample_rate,channels,"
         "width,height,r_frame_rate,pix_fmt", "-of", "json", str(path)],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(result.stdout)


def main() -> int:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe not found")
    config = load_config(ROOT / "config.json")
    script = load_script(
        ROOT / "input/script.json", ROOT / "input/videos", ROOT / "input/images",
        scenes_dir=ROOT / "input/scenes",
    )
    timeline: list[TimelineEntry] = []
    alignments: list[SceneAlignment] = []
    cursor = 0.0
    gap = config.audio.gap_ms / 1000.0
    edge_silences: list[tuple[float, float]] = []
    source_audio_count = 0
    for index, scene in enumerate(script.scenes):
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
        start = float(diagnostics.get("timeline_start", cursor))
        end = float(diagnostics.get("timeline_end", start + diagnostics["audio_duration"]))
        wav = (
            ROOT / "output/voice.wav"
            if config.audio.narration_mode == "continuous"
            else ROOT / f"work/audio/scene_{scene.id:03d}.wav"
        )
        timeline.append(TimelineEntry(scene, wav, end - start, start, end))
        alignments.append(SceneAlignment(scene.id, script.language, words))
        if config.audio.narration_mode == "scene":
            edge_silences.append(_edge_silence(wav))
        if scene.video:
            source_audio_count += probe_audio_duration(
                ROOT / "input/videos" / scene.video, ffprobe
            ) is not None
        cursor = end

    if config.audio.narration_mode == "scene":
        boundary_gaps = [
            edge_silences[index][1] + edge_silences[index + 1][0] + gap
            for index in range(len(edge_silences) - 1)
        ]
    else:
        boundary_gaps = [
            timeline[index + 1].start
            + alignments[index + 1].words[0].start
            - (timeline[index].start + alignments[index].words[-1].end)
            for index in range(len(timeline) - 1)
        ]
    assert max(boundary_gaps) <= 0.300001, boundary_gaps

    cues = create_rolling_cues(tuple(alignments), tuple(timeline), config.subtitles)
    global_words = [
        WordTiming(word.word, word.start + entry.start, word.end + entry.start)
        for entry, alignment in zip(timeline, alignments)
        for word in alignment.words
    ]
    for cue in cues:
        visible = cue.text.replace("\n", " ")
        count = len(visible.split())
        matches = [
            global_words[start:start + count]
            for start in range(len(global_words) - count + 1)
            if " ".join(word.word for word in global_words[start:start + count]) == visible
        ]
        assert matches and any(
            all(word.start <= cue.start + 1e-9 for word in match) for match in matches
        )
    srt = (ROOT / "output/subtitles.srt").read_text(encoding="utf-8")
    ass = (ROOT / "output/subtitles.ass").read_text(encoding="utf-8-sig")
    for cue in cues:
        assert f"{format_srt_timestamp(cue.start)} --> {format_srt_timestamp(cue.end)}" in srt
        assert f"Dialogue: 0,{format_ass_timestamp(cue.start)},{format_ass_timestamp(cue.end)}," in ass

    final_path = latest_final_video_path(ROOT / "output")
    final = _probe_final(final_path, ffprobe)
    video = next(item for item in final["streams"] if item["codec_type"] == "video")
    audio = next(item for item in final["streams"] if item["codec_type"] == "audio")
    assert (video["width"], video["height"], video["r_frame_rate"]) == (1920, 1080, "30/1")
    assert video["codec_name"] == "h264" and video["pix_fmt"] == "yuv420p"
    assert audio["codec_name"] == "aac"
    assert (audio["sample_rate"], audio["channels"]) == ("48000", 2)
    assert abs(float(final["format"]["duration"]) - cursor) <= 1 / 30 + 0.03
    voice_rms = _wav_rms(ROOT / "output/voice.wav")
    sfx_rms = _wav_rms(ROOT / "work/source_sfx.wav")
    assert sfx_rms < voice_rms * 0.25
    assert source_audio_count == len(script.scenes)
    pacing = analyze(
        ROOT / "output/voice.wav", threshold_db=config.audio.pause_threshold_db,
        minimum_ms=config.audio.pause_min_detect_ms,
        ffmpeg=shutil.which("ffmpeg") or "ffmpeg",
        alignment_dir=ROOT / "work/alignment",
    )
    measured = pacing["pcm_pause_summary"]
    assert measured["p90"] <= 0.200001, measured
    assert measured["p95"] <= 0.250001, measured
    assert measured["maximum"] <= 0.300001, measured
    print(json.dumps({
        "final": str(final_path),
        "duration": float(final["format"]["duration"]),
        "scenes": len(script.scenes),
        "source_audio_clips": source_audio_count,
        "boundary_gap_min": min(boundary_gaps),
        "boundary_gap_max": max(boundary_gaps),
        "boundary_gap_average": sum(boundary_gaps) / len(boundary_gaps),
        "voice_to_sfx_rms_ratio": voice_rms / sfx_rms,
        "pacing": measured,
        "no_future_word": "PASS",
        "audio": f"{audio['codec_name']} {audio['sample_rate']}Hz {audio['channels']}ch",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
