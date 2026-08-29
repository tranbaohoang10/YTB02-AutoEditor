import struct
import tempfile
import unittest
import wave
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.config import load_config
from src.layered_manifest import SceneTransition
from src.source_cleanup import flow_watermark_support_image
from src.video_builder import (
    SourceAudioClip, build_source_audio_mix, concat_audio_scenes,
    concat_video_scenes_with_transitions, prepare_video_scene, render_final_video,
    trim_narration_padding,
)
from src.visual_quality import SceneVisualProfile, source_cleanup_geometry


ROOT = Path(__file__).resolve().parents[1]


class VideoBuilderTests(unittest.TestCase):
    def test_prepare_video_scene_keeps_trim_freeze_and_video_only_contract(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ) as run:
            root = Path(directory)
            prepare_video_scene(root / "source.mp4", root / "prepared.mp4", 4.6, config)
        command = run.call_args.args[0]
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("tpad=stop_mode=clone:stop_duration=4.600000", graph)
        self.assertIn("trim=duration=4.600000", graph)
        self.assertIn("force_original_aspect_ratio=decrease", graph)
        self.assertIn("-an", command)

    def test_concat_audio_uses_loudnorm_when_enabled(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ) as run:
            root = Path(directory)
            concat_audio_scenes((root / "scene.wav",), root / "voice.wav", config, root)
        command = run.call_args.args[0]
        filter_value = command[command.index("-af") + 1]
        self.assertEqual(filter_value, "loudnorm=I=-18.0:TP=-1.5:LRA=7.0")

    def test_concat_audio_skips_loudnorm_when_disabled(self) -> None:
        config = load_config(ROOT / "config.json")
        config = replace(
            config, audio=replace(config.audio, normalize_loudness=False)
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ) as run:
            root = Path(directory)
            concat_audio_scenes((root / "scene.wav",), root / "voice.wav", config, root)
        command = run.call_args.args[0]
        self.assertNotIn("-af", command)
        self.assertFalse(any("loudnorm" in item for item in command))

    def test_zero_gap_concat_has_no_hidden_silence_input(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ):
            root = Path(directory)
            concat_audio_scenes(
                (root / "scene_001.wav", root / "scene_002.wav"),
                root / "voice.wav", config, root,
            )
            concat_text = (root / "audio_concat.txt").read_text(encoding="utf-8")
        self.assertIn("scene_001.wav", concat_text)
        self.assertIn("scene_002.wav", concat_text)
        self.assertNotIn("gap.wav", concat_text)

    def test_narration_trim_targets_only_leading_and_trailing_padding(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = (root / "scene_001.wav", root / "scene_002.wav")
            for path in paths:
                samples = (
                    [0] * 7200 + [10000] * 7200 + [0] * 4800
                    + [10000] * 7200 + [0] * 14400
                )
                with wave.open(str(path), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(config.audio.sample_rate)
                    output.writeframes(struct.pack(f"<{len(samples)}h", *samples))
            trim_narration_padding(paths, config)
            with wave.open(str(paths[0]), "rb") as trimmed:
                frames = trimmed.readframes(trimmed.getnframes())
                duration = trimmed.getnframes() / trimmed.getframerate()
            samples_after = struct.unpack(f"<{len(frames) // 2}h", frames)
        self.assertLessEqual(duration, 0.92)
        self.assertGreaterEqual(duration, 0.88)
        longest_zero_run = 0
        current_zero_run = 0
        for sample in samples_after:
            if sample == 0:
                current_zero_run += 1
                longest_zero_run = max(longest_zero_run, current_zero_run)
            else:
                current_zero_run = 0
        self.assertGreaterEqual(longest_zero_run, 4800)

    def test_source_audio_mix_trims_fades_delays_and_never_loops(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ) as run:
            root = Path(directory)
            created = build_source_audio_mix(
                (SourceAudioClip(root / "flow.mp4", 1.5, 1.0),),
                root / "source_sfx.wav", 4.0, config,
            )
        self.assertTrue(created)
        command = run.call_args.args[0]
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("atrim=start=0:duration=1.000000", graph)
        self.assertIn("volume=-18.000dB", graph)
        self.assertIn("afade=t=in:st=0:d=0.120000", graph)
        self.assertIn("afade=t=out:st=0.880000:d=0.120000", graph)
        self.assertIn("adelay=1500:all=1", graph)
        self.assertIn("apad=whole_dur=4.000000", graph)
        self.assertNotIn("aloop", graph)

    def test_empty_source_audio_mix_is_optional(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ) as run:
            root = Path(directory)
            self.assertFalse(
                build_source_audio_mix((), root / "source_sfx.wav", 2.0, config)
            )
        run.assert_not_called()

    def test_all_transition_presets_map_to_ffmpeg_xfade_and_preserve_offsets(self) -> None:
        config = load_config(ROOT / "config.json")
        transitions = (
            "crossfade", "paper_swipe", "paper_slide", "paper_wipe",
            "collage_push", "push_left", "push_right", "zoom_fade",
        )
        expected = (
            "fade", "wipeleft", "slideleft", "wiperight",
            "slideright", "slideleft", "slideright", "zoomin",
        )
        for transition, ffmpeg_name in zip(transitions, expected):
            with self.subTest(transition=transition), tempfile.TemporaryDirectory() as directory, patch(
                "src.video_builder.run_media_command"
            ) as run:
                root = Path(directory)
                concat_video_scenes_with_transitions(
                    (root / "a.mp4", root / "b.mp4"), (2.0, 3.0),
                    (SceneTransition(transition, 0.4),), root / "out.mp4", config,
                )
            command = run.call_args.args[0]
            graph = command[command.index("-filter_complex") + 1]
            self.assertIn(f"transition={ffmpeg_name}", graph)
            self.assertIn("duration=0.400000:offset=1.600000", graph)
            self.assertIn("tpad=stop_mode=clone:stop_duration=0.400000", graph)

    def test_none_transition_is_effective_hard_cut_of_one_frame(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ) as run:
            root = Path(directory)
            concat_video_scenes_with_transitions(
                (root / "a.mp4", root / "b.mp4"), (1.0, 1.0),
                (SceneTransition(),), root / "out.mp4", config,
            )
        graph = run.call_args.args[0][run.call_args.args[0].index("-filter_complex") + 1]
        self.assertIn("duration=0.033333:offset=0.966667", graph)

    def test_transition_settle_reveals_new_scene_before_narration_boundary(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ) as run:
            root = Path(directory)
            concat_video_scenes_with_transitions(
                (root / "a.mp4", root / "b.mp4"), (2.0, 3.0),
                (SceneTransition("paper_swipe", 0.20, 0.066667),),
                root / "out.mp4", config,
            )
        graph = run.call_args.args[0][run.call_args.args[0].index("-filter_complex") + 1]
        self.assertIn("stop_duration=0.266667", graph)
        self.assertIn("duration=0.200000:offset=1.733333", graph)

    def test_long_freeze_tail_uses_deterministic_zoom_pan_mask(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ) as run:
            root = Path(directory)
            prepare_video_scene(
                root / "scene_07.mp4", root / "out.mp4", 5.2, config,
                source_duration=4.0,
            )
        command = run.call_args.args[0]
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("zoompan=", graph)
        self.assertIn("concat=n=2:v=1:a=0", graph)
        self.assertIn("trim=duration=5.200000", graph)

    def test_short_freeze_tail_keeps_stable_clone_path(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ) as run:
            root = Path(directory)
            prepare_video_scene(
                root / "scene_05.mp4", root / "out.mp4", 4.2, config,
                source_duration=4.0,
            )
        command = run.call_args.args[0]
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("tpad=stop_mode=clone", graph)
        self.assertNotIn("zoompan=", graph)

    def test_video_profile_applies_safe_edge_crop_before_quality_filters(self) -> None:
        config = load_config(ROOT / "config.json")
        config = replace(
            config,
            source_cleanup=replace(config.source_cleanup, strategy="safe_edge_crop"),
        )
        profile = SceneVisualProfile(
            3, "video", 0.08, 0.01, 0.08, "high", "low", True,
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ) as run:
            root = Path(directory)
            prepare_video_scene(
                root / "scene_03.mp4", root / "out.mp4", 3.0, config,
                source_duration=4.0, visual_profile=profile,
            )
        command = run.call_args.args[0]
        graph = command[command.index("-filter_complex") + 1]
        self.assertEqual(command.count("-i"), 1)
        self.assertIn("crop=1700:956:0:0", graph)
        self.assertLess(graph.index("crop=1700:956:0:0"), graph.index("eq=contrast="))
        self.assertIn("vignette=angle=", graph)
        self.assertIn("zoompan=", graph)

    def test_default_cleanup_streams_local_frequency_reconstruction_before_quality(self) -> None:
        config = load_config(ROOT / "config.json")
        config = replace(
            config,
            source_cleanup=replace(
                config.source_cleanup, strategy="frequency_selective_reconstruct"
            ),
        )
        profile = SceneVisualProfile(
            3, "video", 0.08, 0.01, 0.08, "high", "low", True,
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_frequency_cleanup_pipeline"
        ) as run:
            root = Path(directory)
            prepare_video_scene(
                root / "scene_03.mp4", root / "out.mp4", 3.0, config,
                source_duration=4.0, visual_profile=profile,
            )
        command = run.call_args.args[2]
        graph = command[command.index("-filter_complex") + 1]
        self.assertEqual(command.count("-i"), 1)
        self.assertIn("pipe:0", command)
        self.assertEqual(run.call_args.kwargs["geometry"], (1680, 824, 200, 200))
        self.assertEqual(run.call_args.kwargs["decode_duration"], 3.0)
        self.assertIn("setsar=1", graph)
        self.assertNotIn("median=", graph)
        self.assertNotIn("alphamerge", graph)
        self.assertNotIn("overlay=", graph)
        self.assertNotIn("crop=1700:956:0:0", graph)
        self.assertNotIn("paper_corner_patch", " ".join(command))
        self.assertLess(graph.index("setsar=1"), graph.index("eq=contrast="))

    def test_cleanup_motion_keeps_bottom_right_roi_anchored(self) -> None:
        config = load_config(ROOT / "config.json")
        config = replace(
            config,
            source_cleanup=replace(
                config.source_cleanup, strategy="frequency_selective_reconstruct"
            ),
        )
        profile = SceneVisualProfile(
            3, "video", 0.08, 0.01, 0.08, "high", "low", True,
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_frequency_cleanup_pipeline"
        ) as run:
            root = Path(directory)
            prepare_video_scene(
                root / "scene_03.mp4", root / "out.mp4", 5.2, config,
                source_duration=4.0, visual_profile=profile,
            )
        command = run.call_args.args[2]
        graph = command[command.index("-filter_complex") + 1]
        self.assertEqual(
            graph.count("x='iw-iw/zoom':y='ih-ih/zoom'"),
            2,
        )

    def test_fast_cover_skips_reconstruction_and_does_not_crop_or_zoom(self) -> None:
        config = load_config(ROOT / "config.json")
        profile = SceneVisualProfile(
            3, "video", 0.08, 0.01, 0.08, "normal", "normal", True,
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_frequency_cleanup_pipeline"
        ) as reconstruct, patch("src.video_builder.run_media_command") as run:
            root = Path(directory)
            prepare_video_scene(
                root / "scene_03.mp4", root / "out.mp4", 3.0, config,
                source_duration=4.0, visual_profile=profile,
                cleanup_cache_dir=root / "cache",
            )
        reconstruct.assert_not_called()
        command = run.call_args.args[0]
        graph = command[command.index("-filter_complex") + 1]
        self.assertEqual(command.count("-i"), 1)
        self.assertNotIn("pipe:0", command)
        self.assertNotIn("crop=", graph)
        self.assertNotIn("zoompan=", graph)
        self.assertNotIn("overlay=", graph)
        self.assertFalse((root / "cache").exists())

    def test_fast_cover_uses_one_official_logo_before_subtitles(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ) as run:
            root = Path(directory)
            render_final_video(
                root / "video.mp4", root / "voice.wav", root / "subtitle.ass",
                root / "final.mp4", config,
            )
        command = run.call_args.args[0]
        video_filter = command[command.index("-vf") + 1]
        self.assertEqual(video_filter.count("movie="), 1)
        self.assertEqual(video_filter.count("l0ki_archives_logo.png"), 1)
        self.assertIn("nullsrc=s=224x224", video_filter)
        self.assertIn("scale=224:224:force_original_aspect_ratio=decrease", video_filter)
        self.assertIn("overlay=x=W-w-20:y=H-h-20", video_filter)
        self.assertLess(video_filter.index("[in][coverbadge]overlay="),
                        video_filter.index("ass=filename="))
        self.assertNotIn("brandmark", video_filter)
        self.assertNotIn("brandshadow", video_filter)
        self.assertNotIn("drawtext=", video_filter)
        self.assertNotIn("Hau Nguyen", video_filter)

    def test_fast_cover_circle_contains_complete_measured_gemini_envelope(self) -> None:
        config = load_config(ROOT / "config.json")
        cleanup = config.source_cleanup
        x, y, width, height = source_cleanup_geometry(
            config.video.width, config.video.height, cleanup,
        )
        support = np.asarray(flow_watermark_support_image(width, height, 0)) > 0
        support_y, support_x = np.where(support)
        support_x += x
        support_y += y
        size = cleanup.cover_logo_width
        left = config.video.width - size - cleanup.cover_margin_right
        top = config.video.height - size - cleanup.cover_margin_bottom
        center_x = left + (size - 1) / 2
        center_y = top + (size - 1) / 2
        radius = size / 2 - 2
        self.assertTrue(np.all(
            (support_x - center_x) ** 2 + (support_y - center_y) ** 2
            <= radius ** 2
        ))

    def test_final_encode_signals_limited_bt709_contract(self) -> None:
        config = load_config(ROOT / "config.json")
        config = replace(
            config,
            source_cleanup=replace(
                config.source_cleanup, strategy="frequency_selective_reconstruct"
            ),
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ) as run:
            root = Path(directory)
            render_final_video(
                root / "video.mp4", root / "voice.wav", root / "subtitle.ass",
                root / "final.mp4", config,
            )
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("-color_range") + 1], "tv")
        self.assertEqual(command[command.index("-colorspace") + 1], "bt709")
        self.assertIn("format=yuv420p,setparams=range=tv", command[command.index("-vf") + 1])
        self.assertEqual(command[command.index("-ar") + 1], "48000")
        self.assertEqual(command[command.index("-ac") + 1], "2")
        self.assertIn(
            "pan=stereo|c0=0.707107*c0|c1=0.707107*c0",
            command[command.index("-af") + 1],
        )
        video_filter = command[command.index("-vf") + 1]
        self.assertIn("ass=filename=", video_filter)
        self.assertIn("l0ki_archives_logo.png", video_filter)
        self.assertEqual(video_filter.count("movie="), 1)
        self.assertIn("scale=76:-1:flags=lanczos", video_filter)
        self.assertIn("split=2[brandcore_src][brandshadow_src]", video_filter)
        self.assertIn("colorchannelmixer=aa=0.640[brandmark]", video_filter)
        self.assertIn("lutrgb=r=255:g=255:b=255", video_filter)
        self.assertIn("gblur=sigma=0.450", video_filter)
        self.assertIn("colorchannelmixer=aa=0.160[brandshadow]", video_filter)
        self.assertIn("overlay=x=W-w-20+1:y=H-h-20+1", video_filter)
        self.assertIn("overlay=x=W-w-20:y=H-h-20", video_filter)
        self.assertNotIn("Hau Nguyen", video_filter)
        self.assertNotIn("drawtext=", video_filter)
        self.assertEqual(video_filter.count("overlay="), 2)
        self.assertLess(video_filter.index("ass="), video_filter.index("overlay="))

    def test_final_mix_keeps_narration_primary_and_adds_source_sfx(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ) as run:
            root = Path(directory)
            sfx = root / "source_sfx.wav"
            render_final_video(
                root / "video.mp4", root / "voice.wav", root / "subtitle.ass",
                root / "final.mp4", config, sfx,
            )
        command = run.call_args.args[0]
        inputs = [command[index + 1] for index, item in enumerate(command) if item == "-i"]
        self.assertEqual(inputs[-1], str(sfx))
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("[voice][sfx]amix=inputs=2:duration=first", graph)
        self.assertIn("normalize=0", graph)
        self.assertIn("loudnorm=I=-18.0:TP=-1.5:LRA=7.0[mixed]", graph)
        self.assertIn("pan=stereo|c0=0.707107*c0|c1=0.707107*c0[voice]", graph)
        self.assertNotIn("volume=", graph.split("[voice]")[0])

    def test_final_mix_accepts_source_and_transition_sfx_as_separate_layers(self) -> None:
        config = load_config(ROOT / "config.json")
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.video_builder.run_media_command"
        ) as run:
            root = Path(directory)
            render_final_video(
                root / "video.mp4", root / "voice.wav", root / "subtitle.ass",
                root / "final.mp4", config, root / "source.wav", root / "transition.wav",
            )
        command = run.call_args.args[0]
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("[voice][sfx][transition]amix=inputs=3:duration=first", graph)
        self.assertIn("normalize=0", graph)


if __name__ == "__main__":
    unittest.main()
