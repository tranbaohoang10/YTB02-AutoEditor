import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.config import load_config
from src.image_assets import VisualAsset
from src.models import Scene, TimelineEntry
from src.pipeline import _prepare_scenes
from src.source_cleanup_cache import (
    cleanup_cache_identity, get_or_create_cleanup_cache,
)
from src.visual_quality import SceneVisualProfile


ROOT = Path(__file__).resolve().parents[1]
VALID_PROBE = {
    "width": 1920, "height": 1080, "fps": 30.0, "duration": 2.0,
}


class SourceCleanupCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        config = load_config(ROOT / "config.json")
        self.config = replace(
            config,
            source_cleanup=replace(
                config.source_cleanup, strategy="frequency_selective_reconstruct"
            ),
        )

    @staticmethod
    def _create_fake_cache(*args, **kwargs) -> None:
        Path(args[2][-1]).write_bytes(b"deterministic-cleaned-video")

    def test_first_run_miss_then_second_run_hit_without_cleanup(self) -> None:
        events: list[str] = []
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.source_cleanup_cache.probe_video", return_value=VALID_PROBE
        ), patch(
            "src.source_cleanup_cache.run_frequency_cleanup_pipeline",
            side_effect=self._create_fake_cache,
        ) as cleanup:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"source-v1")
            first = get_or_create_cleanup_cache(
                source, root / "cache", 2.0, self.config, progress=events.append
            )
            second = get_or_create_cleanup_cache(
                source, root / "cache", 2.0, self.config, progress=events.append
            )
        self.assertFalse(first.hit)
        self.assertTrue(second.hit)
        self.assertEqual(first.path, second.path)
        self.assertEqual(cleanup.call_count, 1)
        self.assertEqual(events, ["MISS", "PROCESSING", "HIT"])

    def test_source_bytes_config_and_implementation_change_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(b"source-v1")
            original, _ = cleanup_cache_identity(source, self.config)
            source.write_bytes(b"source-v2")
            changed_source, _ = cleanup_cache_identity(source, self.config)
            changed_config, _ = cleanup_cache_identity(
                source,
                replace(
                    self.config,
                    source_cleanup=replace(self.config.source_cleanup, feather_px=7),
                ),
            )
            with patch(
                "src.source_cleanup_cache.CLEANUP_IMPLEMENTATION_VERSION", "next-version"
            ):
                changed_implementation, _ = cleanup_cache_identity(source, self.config)
        self.assertEqual(len({
            original, changed_source, changed_config, changed_implementation,
        }), 4)

    def test_corrupt_artifact_is_rejected_and_republished(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.source_cleanup_cache.probe_video", return_value=VALID_PROBE
        ), patch(
            "src.source_cleanup_cache.run_frequency_cleanup_pipeline",
            side_effect=self._create_fake_cache,
        ) as cleanup:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            first = get_or_create_cleanup_cache(source, root / "cache", 2.0, self.config)
            first.path.write_bytes(b"corrupt")
            rebuilt = get_or_create_cleanup_cache(source, root / "cache", 2.0, self.config)
            rebuilt_bytes = rebuilt.path.read_bytes()
        self.assertFalse(rebuilt.hit)
        self.assertEqual(cleanup.call_count, 2)
        self.assertEqual(rebuilt_bytes, b"deterministic-cleaned-video")

    def test_valid_cache_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.source_cleanup_cache.probe_video", return_value=VALID_PROBE
        ), patch(
            "src.source_cleanup_cache.run_frequency_cleanup_pipeline",
            side_effect=self._create_fake_cache,
        ), patch("src.source_cleanup_cache.os.replace", wraps=os.replace) as publish:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            get_or_create_cleanup_cache(source, root / "cache", 2.0, self.config)
            publish.reset_mock()
            result = get_or_create_cleanup_cache(source, root / "cache", 2.0, self.config)
        self.assertTrue(result.hit)
        publish.assert_not_called()

    def test_publish_uses_temporary_files_and_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.source_cleanup_cache.probe_video", return_value=VALID_PROBE
        ), patch(
            "src.source_cleanup_cache.run_frequency_cleanup_pipeline",
            side_effect=self._create_fake_cache,
        ), patch("src.source_cleanup_cache.os.replace", wraps=os.replace) as publish:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            result = get_or_create_cleanup_cache(source, root / "cache", 2.0, self.config)
        self.assertEqual(publish.call_count, 2)
        calls = publish.call_args_list
        self.assertIn(".tmp.mp4", calls[0].args[0].name)
        self.assertEqual(calls[0].args[1], result.path)
        self.assertIn(".tmp.json", calls[1].args[0].name)
        self.assertEqual(calls[1].args[1], result.path.with_suffix(".json"))

    def test_ffprobe_contract_failure_forces_miss(self) -> None:
        invalid = {**VALID_PROBE, "width": 1}
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.source_cleanup_cache.probe_video",
            side_effect=[VALID_PROBE, invalid, VALID_PROBE, invalid],
        ), patch(
            "src.source_cleanup_cache.run_frequency_cleanup_pipeline",
            side_effect=self._create_fake_cache,
        ) as cleanup:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            get_or_create_cleanup_cache(source, root / "cache", 2.0, self.config)
            rebuilt = get_or_create_cleanup_cache(source, root / "cache", 2.0, self.config)
        self.assertFalse(rebuilt.hit)
        self.assertEqual(cleanup.call_count, 2)

    def test_manifest_records_content_identity_and_media_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.source_cleanup_cache.probe_video", return_value=VALID_PROBE
        ), patch(
            "src.source_cleanup_cache.run_frequency_cleanup_pipeline",
            side_effect=self._create_fake_cache,
        ):
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            result = get_or_create_cleanup_cache(source, root / "cache", 2.0, self.config)
            manifest = json.loads(result.path.with_suffix(".json").read_text("utf-8"))
            expected_source_hash = cleanup_cache_identity(source, self.config)[1]["source_sha256"]
        identity = manifest["identity"]
        self.assertEqual(identity["source_sha256"], expected_source_hash)
        self.assertEqual(identity["cleanup_strategy"], "frequency_selective_reconstruct")
        self.assertEqual(identity["video"], {"width": 1920, "height": 1080, "fps": 30})
        self.assertIn("implementation_version", identity)
        self.assertIn("schema_version", identity)

    def test_step_seven_reports_scene_cache_status_and_processing(self) -> None:
        scene = Scene(1, "source.mp4", "Text")
        timeline = (TimelineEntry(scene, Path("voice.wav"), 2.0, 0.0, 2.0),)
        profile = SceneVisualProfile(
            1, "video", 0.1, 0.1, 0.1, "normal", "normal", True,
        )

        def report_cache(*args, **kwargs) -> None:
            kwargs["cleanup_progress"]("MISS")
            kwargs["cleanup_progress"]("PROCESSING")

        with tempfile.TemporaryDirectory() as directory, patch(
            "src.pipeline.probe_duration", return_value=2.0
        ), patch(
            "src.pipeline.prepare_video_scene", side_effect=report_cache
        ) as prepare, patch("builtins.print") as output:
            root = Path(directory)
            _prepare_scenes(
                timeline, {1: VisualAsset("video", root / "source.mp4")},
                root / "scenes", root / "motion", self.config, "local",
                visual_profiles={1: profile},
            )
        lines = [call.args[0] for call in output.call_args_list]
        self.assertIn("       Scene 01 | cleanup cache MISS", lines)
        self.assertIn("                processing...", lines)
        self.assertEqual(
            prepare.call_args.kwargs["cleanup_cache_dir"],
            root / "cache" / "source_cleanup",
        )


if __name__ == "__main__":
    unittest.main()
