from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.config import load_config
from src.final_assembler import (
    AssemblyPlan,
    MediaContract,
    PartCandidate,
    SelectedPart,
    TopicManifest,
    discover_latest_parts,
    expected_media_contract,
    load_topic_manifest,
    next_final_path,
    probe_media,
    publish_assembly,
    reserve_final_output,
    run_final_assembly,
    validate_final_candidate,
    validate_selected_parts,
)
from src.models import AutoEditorError


ROOT = Path(__file__).resolve().parents[1]


def _topic_file(root: Path, expected_parts: int = 3) -> Path:
    path = root / "topic.json"
    path.write_text(json.dumps({
        "topic": "Black Wednesday",
        "expected_parts": expected_parts,
        "production_language": "en",
        "experimental_languages": ["vi"],
    }), encoding="utf-8")
    return path


def _candidate(
    root: Path,
    part: int,
    version: int,
    *,
    language: str = "en",
    topic_slug: str = "Black_Wednesday",
    name: str | None = None,
    metadata: dict[str, object] | None = None,
) -> Path:
    directory = root / topic_slug / f"Part_{part:02d}" / language.upper()
    directory.mkdir(parents=True, exist_ok=True)
    filename = name or f"{topic_slug}_Part_{part:02d}_{language.upper()}_{version}.mp4"
    path = directory / filename
    path.write_bytes(b"fixture")
    if metadata is not None:
        path.with_suffix(".json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
    return path


def _valid_metadata(part: int, version: int, language: str = "en") -> dict[str, object]:
    tag = language.upper()
    return {
        "topic": "Black Wednesday",
        "part": part,
        "language": language,
        "video": f"Black_Wednesday_Part_{part:02d}_{tag}_{version}.mp4",
    }


def _manifest(expected_parts: int = 3) -> TopicManifest:
    return TopicManifest("Black Wednesday", expected_parts, "en", ("vi",))


def _unit_config():
    return load_config(ROOT / "config.json")


def _selected_part(
    root: Path, part: int, version: int, contract: MediaContract, duration: float = 1.0
) -> SelectedPart:
    path = root / f"Black_Wednesday_Part_{part:02d}_EN_{version}.mp4"
    path.write_bytes(b"source")
    return SelectedPart(part, version, path, duration, contract)


class FinalAssemblerDiscoveryTests(unittest.TestCase):
    def test_highest_version_is_selected_independently_for_every_part(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for part, versions in ((1, (8, 10, 9)), (2, (4, 3)), (3, (2, 1))):
                for version in versions:
                    _candidate(root, part, version)
            selected = discover_latest_parts(_manifest(), root, "en")
        self.assertEqual(
            [(item.part, item.version) for item in selected],
            [(1, 10), (2, 4), (3, 2)],
        )

    def test_old_versions_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for version in (1, 2, 25, 7):
                _candidate(root, 1, version)
            selected = discover_latest_parts(_manifest(1), root, "en")
        self.assertEqual(selected[0].version, 25)

    def test_filesystem_mtime_is_not_used(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            newest_number = _candidate(root, 1, 10)
            lower_number = _candidate(root, 1, 9)
            os.utime(newest_number, (1, 1))
            os.utime(lower_number, (2_000_000_000, 2_000_000_000))
            selected = discover_latest_parts(_manifest(1), root, "en")
        self.assertEqual(selected[0].version, 10)

    def test_parts_remain_in_numeric_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for part in (3, 1, 2):
                _candidate(root, part, 1)
            selected = discover_latest_parts(_manifest(), root, "en")
        self.assertEqual([item.part for item in selected], [1, 2, 3])

    def test_missing_first_part_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _candidate(root, 2, 1)
            _candidate(root, 3, 1)
            with self.assertRaisesRegex(AutoEditorError, "Part_01"):
                discover_latest_parts(_manifest(), root, "en")

    def test_missing_middle_part_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _candidate(root, 1, 1)
            _candidate(root, 3, 1)
            with self.assertRaisesRegex(AutoEditorError, "Part_02"):
                discover_latest_parts(_manifest(), root, "en")

    def test_missing_final_part_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _candidate(root, 1, 1)
            _candidate(root, 2, 1)
            with self.assertRaisesRegex(AutoEditorError, "Part_03"):
                discover_latest_parts(_manifest(), root, "en")

    def test_malformed_filename_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _candidate(
                root, 1, 0,
                name="Black_Wednesday_Part_01_EN_latest.mp4",
            )
            with self.assertRaisesRegex(AutoEditorError, "filename"):
                discover_latest_parts(_manifest(1), root, "en")

    def test_wrong_topic_filename_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _candidate(
                root, 1, 1,
                name="Another_Topic_Part_01_EN_99.mp4",
            )
            with self.assertRaisesRegex(AutoEditorError, "production scope"):
                discover_latest_parts(_manifest(1), root, "en")

    def test_wrong_language_filename_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _candidate(
                root, 1, 1,
                name="Black_Wednesday_Part_01_VI_99.mp4",
            )
            with self.assertRaisesRegex(AutoEditorError, "production scope"):
                discover_latest_parts(_manifest(1), root, "en")

    def test_metadata_part_mismatch_rejects_latest_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _candidate(root, 1, 3)
            bad = _valid_metadata(1, 4)
            bad["part"] = 2
            _candidate(root, 1, 4, metadata=bad)
            selected = discover_latest_parts(_manifest(1), root, "en")
        self.assertEqual(selected[0].version, 3)

    def test_metadata_language_mismatch_rejects_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad = _valid_metadata(1, 1)
            bad["language"] = "vi"
            _candidate(root, 1, 1, metadata=bad)
            with self.assertRaisesRegex(AutoEditorError, "language"):
                discover_latest_parts(_manifest(1), root, "en")

    def test_metadata_topic_mismatch_rejects_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad = _valid_metadata(1, 1)
            bad["topic"] = "Other"
            _candidate(root, 1, 1, metadata=bad)
            with self.assertRaisesRegex(AutoEditorError, "topic"):
                discover_latest_parts(_manifest(1), root, "en")

    def test_metadata_video_filename_mismatch_rejects_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad = _valid_metadata(1, 1)
            bad["video"] = "wrong.mp4"
            _candidate(root, 1, 1, metadata=bad)
            with self.assertRaisesRegex(AutoEditorError, "video"):
                discover_latest_parts(_manifest(1), root, "en")


class FinalAssemblerValidationTests(unittest.TestCase):
    def test_topic_manifest_loads_english_production_and_vi_experimental(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            loaded = load_topic_manifest(_topic_file(Path(directory)))
        self.assertEqual(loaded.production_language, "en")
        self.assertEqual(loaded.experimental_languages, ("vi",))

    def test_video_media_contract_mismatch_is_rejected(self) -> None:
        config = _unit_config()
        expected = expected_media_contract(config)
        actual = replace(expected, width=1280)
        candidate = PartCandidate(2, 1, Path("part.mp4"))
        with patch("src.final_assembler.probe_media", return_value=(actual, 2.0)):
            with self.assertRaisesRegex(AutoEditorError, "Part_02 media contract"):
                validate_selected_parts((candidate,), config)

    def test_audio_media_contract_mismatch_is_rejected(self) -> None:
        config = _unit_config()
        expected = expected_media_contract(config)
        actual = replace(expected, sample_rate=44_100, channel_layout="mono", channels=1)
        candidate = PartCandidate(1, 1, Path("part.mp4"))
        with patch("src.final_assembler.probe_media", return_value=(actual, 2.0)):
            with self.assertRaisesRegex(AutoEditorError, "48000Hz stereo/2ch"):
                validate_selected_parts((candidate,), config)

    def test_duration_validation_rejects_out_of_tolerance_final(self) -> None:
        config = _unit_config()
        contract = expected_media_contract(config)
        with patch("src.final_assembler.probe_media", return_value=(contract, 12.0)):
            with self.assertRaisesRegex(AutoEditorError, "duration validation"):
                validate_final_candidate(Path("final.mp4"), contract, 9.0, 3, "ffprobe")


class FinalAssemblerPublicationTests(unittest.TestCase):
    def test_final_and_en_directories_are_created(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reservation = reserve_final_output(root, "Black_Wednesday", "en")
            self.assertEqual(
                reservation.final_path.parent,
                root / "Black_Wednesday_FINAL" / "EN",
            )
            self.assertTrue(reservation.final_path.is_file())

    def test_final_numbering_is_independent_and_does_not_fill_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            en_dir = root / "Black_Wednesday_FINAL" / "EN"
            vi_dir = root / "Black_Wednesday_FINAL" / "VI"
            en_dir.mkdir(parents=True)
            vi_dir.mkdir(parents=True)
            for version in (1, 2, 5):
                (en_dir / f"Black_Wednesday_FINAL_EN_{version}.mp4").write_bytes(b"old")
            (vi_dir / "Black_Wednesday_FINAL_VI_12.mp4").write_bytes(b"old")
            (en_dir / "Other_FINAL_EN_99.mp4").write_bytes(b"other")
            planned = next_final_path(root, "Black_Wednesday", "en")
        self.assertEqual(planned.name, "Black_Wednesday_FINAL_EN_6.mp4")

    def test_reservation_never_overwrites_existing_final(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            final_dir = root / "Black_Wednesday_FINAL" / "EN"
            final_dir.mkdir(parents=True)
            original = final_dir / "Black_Wednesday_FINAL_EN_1.mp4"
            original.write_bytes(b"keep")
            reservation = reserve_final_output(root, "Black_Wednesday", "en")
            self.assertEqual(reservation.version, 2)
            self.assertEqual(original.read_bytes(), b"keep")

    def test_orphan_manifest_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            final_dir = root / "Black_Wednesday_FINAL" / "EN"
            final_dir.mkdir(parents=True)
            orphan = final_dir / "Black_Wednesday_FINAL_EN_1.json"
            orphan.write_bytes(b"keep")
            with self.assertRaisesRegex(AutoEditorError, "Manifest FINAL"):
                reserve_final_output(root, "Black_Wednesday", "en")
            self.assertEqual(orphan.read_bytes(), b"keep")
            self.assertFalse((final_dir / "Black_Wednesday_FINAL_EN_1.mp4").exists())

    def test_atomic_publication_and_manifest_record_exact_sources(self) -> None:
        config = _unit_config()
        contract = expected_media_contract(config)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parts = tuple(
                _selected_part(root, part, version, contract, float(part))
                for part, version in ((1, 10), (2, 4), (3, 2))
            )
            plan = AssemblyPlan(
                _manifest(), "en", "Black_Wednesday", parts, 6.0,
                root / "planned.mp4",
            )
            commands: list[list[str]] = []

            def fake_run(command, **_kwargs):
                commands.append(list(command))
                Path(command[-1]).write_bytes(b"complete-final")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch("src.final_assembler.subprocess.run", side_effect=fake_run),
                patch("src.final_assembler.validate_final_candidate", return_value=6.0),
            ):
                video, manifest, payload = publish_assembly(plan, config, root)
            self.assertEqual(video.read_bytes(), b"complete-final")
            self.assertTrue(manifest.is_file())
            self.assertEqual([item["version"] for item in payload["parts"]], [10, 4, 2])
            self.assertEqual(payload["output"], video.name)
            self.assertIn("copy", commands[0])
            self.assertFalse(any(path.name.startswith(".") for path in video.parent.iterdir()))

    def test_failed_concat_cleans_reservation_and_temporary_files(self) -> None:
        config = _unit_config()
        contract = expected_media_contract(config)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parts = (_selected_part(root, 1, 1, contract),)
            plan = AssemblyPlan(
                _manifest(1), "en", "Black_Wednesday", parts, 1.0,
                root / "planned.mp4",
            )

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"partial")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch("src.final_assembler.subprocess.run", side_effect=fake_run),
                patch(
                    "src.final_assembler.validate_final_candidate",
                    side_effect=AutoEditorError("forced validation failure"),
                ),
            ):
                with self.assertRaisesRegex(AutoEditorError, "forced"):
                    publish_assembly(plan, config, root)
            final_dir = root / "Black_Wednesday_FINAL" / "EN"
            self.assertEqual(list(final_dir.iterdir()), [])

    def test_dry_run_does_not_create_final_output(self) -> None:
        config = _unit_config()
        contract = expected_media_contract(config)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            topic = _topic_file(root, 1)
            _candidate(output, 1, 1)
            with (
                patch("src.final_assembler.require_executable"),
                patch("src.final_assembler.probe_media", return_value=(contract, 2.0)),
                redirect_stdout(StringIO()),
            ):
                result = run_final_assembly(
                    topic, ROOT / "config.json", output,
                    language="en", dry_run=True,
                )
            self.assertIsNone(result)
            self.assertFalse((output / "Black_Wednesday_FINAL").exists())

    def test_vi_language_path_remains_structurally_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _candidate(root, 1, 7, language="vi")
            selected = discover_latest_parts(_manifest(1), root, "vi")
            planned = next_final_path(root, "Black_Wednesday", "vi")
        self.assertEqual((selected[0].version, planned.parent.name), (7, "VI"))


class FinalAssemblerRealMediaTests(unittest.TestCase):
    def test_real_ffmpeg_three_part_stream_copy_concat_is_about_nine_seconds(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        self.assertIsNotNone(ffmpeg)
        self.assertIsNotNone(ffprobe)
        config = load_config(ROOT / "config.json")
        config = replace(
            config,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            video=replace(config.video, width=320, height=180),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            topic = _topic_file(root)
            for part, version, duration, color in (
                (1, 10, 2, "navy"),
                (2, 4, 3, "maroon"),
                (3, 2, 4, "darkgreen"),
            ):
                video = _candidate(
                    output, part, version,
                    metadata=_valid_metadata(part, version),
                )
                subprocess.run([
                    ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i",
                    f"color=c={color}:s=320x180:r=30:d={duration}",
                    "-f", "lavfi", "-i",
                    f"sine=frequency={400 + part * 100}:sample_rate=48000:duration={duration}",
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-ar", "48000", "-ac", "2", "-shortest", str(video),
                ], check=True)
            with patch("src.final_assembler.load_config", return_value=config):
                result = run_final_assembly(
                    topic, ROOT / "config.json", output, language="en"
                )
            self.assertIsNotNone(result)
            final_path, manifest_path = result
            contract, duration = probe_media(final_path, ffprobe)
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(contract, expected_media_contract(config))
        self.assertLessEqual(abs(duration - 9.0), 0.30)
        self.assertEqual([item["version"] for item in payload["parts"]], [10, 4, 2])
        self.assertEqual(payload["duration"], duration)


if __name__ == "__main__":
    unittest.main()
