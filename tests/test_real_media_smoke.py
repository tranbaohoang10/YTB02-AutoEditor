import os
import json
import math
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
from dataclasses import replace
from pathlib import Path

from PIL import Image

from src.config import load_config
from src.ffmpeg_utils import probe_audio_duration, probe_duration
from src.image_motion import prepare_image_scene
from src.layered_composer import render_layered_scene
from src.layered_manifest import SceneTransition, load_layered_manifest
from src.media_qc import probe_video
from src.video_builder import (
    SourceAudioClip, build_source_audio_mix, concat_audio_scenes,
    concat_video_scenes_with_transitions, render_final_video,
    trim_narration_padding,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_sine_wav(
    path: Path, sample_rate: int, segments: list[tuple[float, float]],
) -> None:
    samples: list[int] = []
    cursor = 0
    for duration, amplitude in segments:
        count = round(duration * sample_rate)
        for _ in range(count):
            value = amplitude * math.sin(2.0 * math.pi * 440.0 * cursor / sample_rate)
            samples.append(round(value * 32767))
            cursor += 1
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _wav_rms(path: Path, start: float, duration: float) -> float:
    with wave.open(str(path), "rb") as source:
        source.setpos(round(start * source.getframerate()))
        frames = source.readframes(round(duration * source.getframerate()))
        samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    return math.sqrt(sum(sample * sample for sample in samples) / max(1, len(samples)))


def _probe_streams(path: Path, ffprobe: str) -> dict:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,codec_name,sample_rate,channels",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(result.stdout)


@unittest.skipUnless(os.environ.get("YTB_RUN_REAL_MEDIA") == "1", "real FFmpeg smoke is opt-in")
class RealMediaSmokeTests(unittest.TestCase):
    def test_two_scene_zero_gap_trims_only_edge_padding(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        self.assertIsNotNone(ffmpeg)
        self.assertIsNotNone(ffprobe)
        config = load_config(ROOT / "config.json")
        config = replace(
            config, ffmpeg=ffmpeg, ffprobe=ffprobe,
            audio=replace(config.audio, normalize_loudness=False, gap_ms=0),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenes = (root / "scene_001.wav", root / "scene_002.wav")
            for scene in scenes:
                _write_sine_wav(
                    scene, config.audio.sample_rate,
                    [(0.30, 0.0), (0.30, 0.4), (0.20, 0.0),
                     (0.30, 0.4), (0.60, 0.0)],
                )
            trim_narration_padding(scenes, config)
            durations = [probe_duration(path, ffprobe) for path in scenes]
            voice = root / "voice.wav"
            concat_audio_scenes(scenes, voice, config, root)
            combined = probe_duration(voice, ffprobe)
        self.assertTrue(
            all(0.85 <= duration <= 0.95 for duration in durations), durations
        )
        self.assertLessEqual(abs(combined - sum(durations)), 0.02)
        self.assertLessEqual(2 * config.audio.narration_edge_silence_ms, 100)

    def test_real_source_audio_mix_fade_no_loop_and_valid_final(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        self.assertIsNotNone(ffmpeg)
        self.assertIsNotNone(ffprobe)
        config = load_config(ROOT / "config.json")
        config = replace(
            config, ffmpeg=ffmpeg, ffprobe=ffprobe,
            video=replace(config.video, width=320, height=180, preset="ultrafast"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_with_audio = root / "flow_with_audio.mp4"
            source_without_audio = root / "flow_without_audio.mp4"
            video = root / "video.mp4"
            subprocess.run([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=navy:s=320x180:r=30:d=0.6",
                "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=0.6",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-ac", "2", "-shortest", str(source_with_audio),
            ], check=True)
            subprocess.run([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=320x180:r=30:d=0.6",
                "-an", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", str(source_without_audio),
            ], check=True)
            subprocess.run([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=navy:s=320x180:r=30:d=2.0",
                "-an", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", str(video),
            ], check=True)
            source_duration = probe_audio_duration(source_with_audio, ffprobe)
            self.assertIsNotNone(source_duration)
            self.assertIsNone(probe_audio_duration(source_without_audio, ffprobe))
            sfx = root / "source_sfx.wav"
            self.assertTrue(build_source_audio_mix(
                (SourceAudioClip(source_with_audio, 0.0, min(source_duration, 2.0)),),
                sfx, 2.0, config,
            ))
            voice = root / "voice.wav"
            _write_sine_wav(voice, config.audio.sample_rate, [(2.0, 0.4)])
            subtitle = root / "subtitle.ass"
            subtitle.write_text(
                "[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 180\n"
                "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, "
                "SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
                "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
                "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                "Style: Default,Arial,20,&H00FFFFFF,&H00FFFFFF,&H00000000,"
                "&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
                "MarginV, Effect, Text\n",
                encoding="utf-8",
            )
            final = root / "final.mp4"
            render_final_video(video, voice, subtitle, final, config, sfx)
            info = _probe_streams(final, ffprobe)
            sfx_tail_rms = _wav_rms(sfx, 1.0, 0.5)
            sfx_fade_rms = _wav_rms(sfx, 0.0, 0.03)
            sfx_body_rms = _wav_rms(sfx, 0.20, 0.10)
            voice_rms = _wav_rms(voice, 0.20, 0.10)
        video_stream = next(item for item in info["streams"] if item["codec_type"] == "video")
        audio_stream = next(item for item in info["streams"] if item["codec_type"] == "audio")
        self.assertEqual(video_stream["codec_name"], "h264")
        self.assertEqual(audio_stream["codec_name"], "aac")
        self.assertEqual(audio_stream["sample_rate"], "48000")
        self.assertEqual(audio_stream["channels"], 2)
        self.assertLessEqual(abs(float(info["format"]["duration"]) - 2.0), 0.05)
        self.assertEqual(sfx_tail_rms, 0.0)
        self.assertLess(sfx_fade_rms, sfx_body_rms * 0.5)
        self.assertLess(sfx_body_rms, voice_rms * 0.2)

    def test_jpeg_to_limited_yuv420p_local_motion_real_ffmpeg(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        self.assertIsNotNone(ffmpeg)
        self.assertIsNotNone(ffprobe)
        config = load_config(ROOT / "config.json")
        config = replace(config, ffmpeg=ffmpeg, ffprobe=ffprobe)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "source.jpeg"
            output = root / "motion.mp4"
            Image.new("RGB", (1280, 720), "#d9d1bd").save(image, format="JPEG", quality=92)
            prepare_image_scene(image, output, 2.4, config, "slow_push_in")
            info = probe_video(output, ffprobe)
        self.assertEqual((info["width"], info["height"]), (1920, 1080))
        self.assertEqual(info["codec_name"], "h264")
        self.assertEqual(info["pix_fmt"], "yuv420p")
        self.assertEqual(info["color_range"], "tv")
        self.assertEqual(info["r_frame_rate"], "30/1")
        self.assertLessEqual(abs(info["duration"] - 2.4), 1 / 30 + 0.01)

    def test_real_layered_scene_and_two_scene_transition(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        self.assertIsNotNone(ffmpeg)
        self.assertIsNotNone(ffprobe)
        config = load_config(ROOT / "config.json")
        config = replace(config, ffmpeg=ffmpeg, ffprobe=ffprobe)
        manifest = load_layered_manifest(
            ROOT / "input" / "sample-scenes" / "scene_01",
            expected_width=1920, expected_height=1080,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "layered_1.mp4"
            second = root / "layered_2.mp4"
            final = root / "two_scenes.mp4"
            render_layered_scene(manifest, first, 3.0, config)
            render_layered_scene(manifest, second, 3.0, config)
            concat_video_scenes_with_transitions(
                (first, second), (3.0, 3.0),
                (SceneTransition("paper_wipe", 0.45),), final, config,
            )
            one = probe_video(first, ffprobe)
            two = probe_video(final, ffprobe)
        for info in (one, two):
            self.assertEqual((info["width"], info["height"]), (1920, 1080))
            self.assertEqual(info["codec_name"], "h264")
            self.assertEqual(info["pix_fmt"], "yuv420p")
            self.assertEqual(info["color_range"], "tv")
            self.assertEqual(info["r_frame_rate"], "30/1")
        self.assertLessEqual(abs(one["duration"] - 3.0), 1 / 30 + 0.01)
        self.assertLessEqual(abs(two["duration"] - 6.0), 1 / 30 + 0.02)

    def test_watermark_survives_transition_with_three_audio_layers(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        self.assertIsNotNone(ffmpeg)
        self.assertIsNotNone(ffprobe)
        config = load_config(ROOT / "config.json")
        config = replace(
            config, ffmpeg=ffmpeg, ffprobe=ffprobe,
            video=replace(config.video, width=320, height=180, preset="ultrafast"),
            watermark=replace(
                config.watermark, font_size=20, margin_right=14, margin_bottom=12,
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenes = (root / "left.mp4", root / "right.mp4")
            for scene, color in zip(scenes, ("maroon", "navy")):
                subprocess.run([
                    ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=30:d=1",
                    "-an", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", str(scene),
                ], check=True)
            joined = root / "joined.mp4"
            concat_video_scenes_with_transitions(
                scenes, (1.0, 1.0), (SceneTransition("paper_swipe", 0.25),),
                joined, config,
            )
            voice = root / "voice.wav"
            source_sfx = root / "source.wav"
            transition_sfx = root / "transition.wav"
            _write_sine_wav(voice, 24_000, [(2.0, 0.35)])
            _write_sine_wav(source_sfx, 48_000, [(2.0, 0.02)])
            _write_sine_wav(transition_sfx, 48_000, [(2.0, 0.01)])
            subtitle = root / "subtitle.ass"
            subtitle.write_text(
                "[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 180\n"
                "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, "
                "SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
                "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
                "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                "Style: Default,Arial,20,&H00FFFFFF,&H00FFFFFF,&H00000000,"
                "&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
                "MarginV, Effect, Text\n",
                encoding="utf-8",
            )
            final = root / "final.mp4"
            render_final_video(
                joined, voice, subtitle, final, config, source_sfx, transition_sfx
            )
            frame = root / "during_transition.png"
            subprocess.run([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-ss", "0.88", "-i", str(final), "-frames:v", "1", "-update", "1",
                str(frame),
            ], check=True)
            info = _probe_streams(final, ffprobe)
            with Image.open(frame).convert("RGB") as image:
                crop = image.crop((230, 125, 320, 180))
                neutral_bright = sum(
                    max(pixel) - min(pixel) < 30 and min(pixel) > 120
                    for pixel in crop.getdata()
                )
        audio = next(item for item in info["streams"] if item["codec_type"] == "audio")
        self.assertEqual((audio["codec_name"], audio["sample_rate"], audio["channels"]),
                         ("aac", "48000", 2))
        self.assertGreater(neutral_bright, 3, "l0ki watermark missing during transition")


if __name__ == "__main__":
    unittest.main()
