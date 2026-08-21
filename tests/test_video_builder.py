import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.config import load_config
from src.layered_manifest import SceneTransition
from src.video_builder import (
    concat_audio_scenes, concat_video_scenes_with_transitions, prepare_video_scene,
    render_final_video,
)


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
        vf = command[command.index("-vf") + 1]
        self.assertIn("tpad=stop_mode=clone:stop_duration=4.600000", vf)
        self.assertIn("trim=duration=4.600000", vf)
        self.assertIn("force_original_aspect_ratio=decrease", vf)
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

    def test_all_transition_presets_map_to_ffmpeg_xfade_and_preserve_offsets(self) -> None:
        config = load_config(ROOT / "config.json")
        transitions = ("crossfade", "paper_wipe", "push_left", "push_right", "zoom_fade")
        expected = ("fade", "wipeleft", "slideleft", "slideright", "zoomin")
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
            self.assertIn("duration=0.400000:offset=2.000000", graph)

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
        self.assertIn("duration=0.033333:offset=1.000000", graph)

    def test_final_encode_signals_limited_bt709_contract(self) -> None:
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
        self.assertEqual(command[command.index("-color_range") + 1], "tv")
        self.assertEqual(command[command.index("-colorspace") + 1], "bt709")
        self.assertIn("format=yuv420p,setparams=range=tv", command[command.index("-vf") + 1])


if __name__ == "__main__":
    unittest.main()
