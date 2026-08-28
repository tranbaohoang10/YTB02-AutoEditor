from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Sequence

from .config import AppConfig, load_config
from .ffmpeg_utils import require_executable, write_concat_file
from .models import AutoEditorError
from .output_manager import safe_topic_slug


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_LANGUAGES = {"en", "vi"}
RESERVATION_ATTEMPTS = 100


@dataclass(frozen=True)
class TopicManifest:
    topic: str
    expected_parts: int
    production_language: str
    experimental_languages: tuple[str, ...] = ()


@dataclass(frozen=True)
class PartCandidate:
    part: int
    version: int
    path: Path


@dataclass(frozen=True)
class MediaContract:
    video_codec: str
    width: int
    height: int
    fps: Fraction
    pixel_format: str
    audio_codec: str
    sample_rate: int
    channels: int
    channel_layout: str


@dataclass(frozen=True)
class SelectedPart:
    part: int
    version: int
    path: Path
    duration: float
    contract: MediaContract


@dataclass(frozen=True)
class FinalReservation:
    final_path: Path
    temporary_path: Path
    manifest_path: Path
    temporary_manifest_path: Path
    concat_path: Path
    version: int


@dataclass(frozen=True)
class AssemblyPlan:
    manifest: TopicManifest
    language: str
    topic_slug: str
    selected_parts: tuple[SelectedPart, ...]
    expected_duration: float
    planned_output: Path


def load_topic_manifest(path: Path) -> TopicManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise AutoEditorError(f"Không tìm thấy topic manifest: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AutoEditorError(f"Không đọc được topic manifest {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise AutoEditorError("Topic manifest phải là một JSON object.")
    topic = raw.get("topic")
    expected_parts = raw.get("expected_parts")
    production_language = raw.get("production_language", "en")
    experimental = raw.get("experimental_languages", [])
    if not isinstance(topic, str) or not topic.strip():
        raise AutoEditorError("topic.json: 'topic' phải là chuỗi không rỗng.")
    if (
        isinstance(expected_parts, bool)
        or not isinstance(expected_parts, int)
        or expected_parts <= 0
    ):
        raise AutoEditorError("topic.json: 'expected_parts' phải là số nguyên dương.")
    if production_language not in SUPPORTED_LANGUAGES:
        raise AutoEditorError("topic.json: 'production_language' chỉ hỗ trợ 'en' hoặc 'vi'.")
    if (
        not isinstance(experimental, list)
        or any(item not in SUPPORTED_LANGUAGES for item in experimental)
        or len(set(experimental)) != len(experimental)
    ):
        raise AutoEditorError(
            "topic.json: 'experimental_languages' phải là danh sách EN/VI không trùng."
        )
    return TopicManifest(
        topic=topic.strip(),
        expected_parts=expected_parts,
        production_language=production_language,
        experimental_languages=tuple(experimental),
    )


def _source_pattern(topic_slug: str, part: int, language: str) -> re.Pattern[str]:
    prefix = f"{topic_slug}_Part_{part:02d}_{language.upper()}"
    return re.compile(re.escape(prefix) + r"_([0-9]+)\.mp4\Z")


def _validate_source_metadata(
    candidate: PartCandidate, topic: str, language: str,
) -> str | None:
    metadata_path = candidate.path.with_suffix(".json")
    if not metadata_path.exists():
        return None
    if not metadata_path.is_file():
        return "metadata path không phải file"
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"metadata JSON không hợp lệ: {exc}"
    if not isinstance(payload, dict):
        return "metadata phải là JSON object"
    checks = (
        (payload.get("topic") == topic, "topic"),
        (payload.get("part") == candidate.part, "part"),
        (
            isinstance(payload.get("language"), str)
            and payload["language"].lower() == language,
            "language",
        ),
        (payload.get("video") == candidate.path.name, "video"),
    )
    failed = [name for valid, name in checks if not valid]
    return f"metadata không khớp: {', '.join(failed)}" if failed else None


def discover_latest_parts(
    manifest: TopicManifest, output_root: Path, language: str,
) -> tuple[PartCandidate, ...]:
    if language not in SUPPORTED_LANGUAGES:
        raise AutoEditorError("Language assembler chỉ hỗ trợ EN hoặc VI.")
    topic_slug = safe_topic_slug(manifest.topic)
    selected: list[PartCandidate] = []
    rejected_by_part: dict[int, list[str]] = {}
    found_by_part: dict[int, bool] = {}
    for part in range(1, manifest.expected_parts + 1):
        directory = output_root / topic_slug / f"Part_{part:02d}" / language.upper()
        pattern = _source_pattern(topic_slug, part, language)
        valid: list[PartCandidate] = []
        rejected: list[str] = []
        if directory.is_dir():
            for path in sorted(directory.iterdir(), key=lambda item: item.name):
                if not path.is_file() or path.suffix != ".mp4":
                    continue
                match = pattern.fullmatch(path.name)
                if match is None:
                    rejected.append(f"{path.name}: filename không đúng production scope")
                    continue
                version = int(match.group(1))
                if version <= 0:
                    rejected.append(f"{path.name}: version phải lớn hơn 0")
                    continue
                candidate = PartCandidate(part=part, version=version, path=path)
                metadata_error = _validate_source_metadata(
                    candidate, manifest.topic, language
                )
                if metadata_error:
                    rejected.append(f"{path.name}: {metadata_error}")
                    continue
                valid.append(candidate)
        found_by_part[part] = bool(valid)
        rejected_by_part[part] = rejected
        if valid:
            selected.append(max(valid, key=lambda item: item.version))

    missing = [part for part, found in found_by_part.items() if not found]
    if missing:
        lines = [
            "FINAL assembly cannot continue.",
            "",
            f"TOPIC: {manifest.topic}",
            f"LANGUAGE: {language.upper()}",
            "",
            "MISSING REQUIRED PARTS: " + ", ".join(
                f"Part_{part:02d}" for part in missing
            ),
            "",
            "Found:",
            *(
                f"Part_{part:02d} = {'YES' if found_by_part[part] else 'NO'}"
                for part in range(1, manifest.expected_parts + 1)
            ),
        ]
        rejected = [
            f"Part_{part:02d}: {reason}"
            for part in missing
            for reason in rejected_by_part[part]
        ]
        if rejected:
            lines.extend(("", "Rejected candidates:", *rejected))
        lines.extend(("", "No FINAL video was created."))
        raise AutoEditorError("\n".join(lines))
    return tuple(sorted(selected, key=lambda item: item.part))


def probe_media(path: Path, ffprobe: str) -> tuple[MediaContract, float]:
    command = [
        ffprobe,
        "-v", "error",
        "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,"
        "pix_fmt,sample_rate,channels,channel_layout",
        "-of", "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except OSError as exc:
        raise AutoEditorError(f"Không chạy được ffprobe: {exc}") from exc
    if result.returncode != 0:
        raise AutoEditorError(f"ffprobe không đọc được {path}: {result.stderr.strip()}")
    try:
        payload = json.loads(result.stdout)
        streams = payload["streams"]
        video = next(item for item in streams if item.get("codec_type") == "video")
        audio = next(item for item in streams if item.get("codec_type") == "audio")
        duration = float(payload["format"]["duration"])
        contract = MediaContract(
            video_codec=str(video["codec_name"]),
            width=int(video["width"]),
            height=int(video["height"]),
            fps=Fraction(str(video["r_frame_rate"])),
            pixel_format=str(video["pix_fmt"]),
            audio_codec=str(audio["codec_name"]),
            sample_rate=int(audio["sample_rate"]),
            channels=int(audio["channels"]),
            channel_layout=str(audio["channel_layout"]),
        )
    except (
        KeyError, StopIteration, TypeError, ValueError, ZeroDivisionError,
        json.JSONDecodeError,
    ) as exc:
        raise AutoEditorError(f"Media thiếu video/audio contract hợp lệ: {path}") from exc
    if duration <= 0:
        raise AutoEditorError(f"Media duration không hợp lệ ({duration}): {path}")
    return contract, duration


def expected_media_contract(config: AppConfig) -> MediaContract:
    return MediaContract(
        video_codec="h264",
        width=config.video.width,
        height=config.video.height,
        fps=Fraction(config.video.fps, 1),
        pixel_format="yuv420p",
        audio_codec="aac",
        sample_rate=config.audio.mix_sample_rate,
        channels=2,
        channel_layout="stereo",
    )


def _contract_text(contract: MediaContract) -> str:
    fps = float(contract.fps)
    return (
        f"{contract.width}x{contract.height} {fps:g}fps "
        f"{contract.video_codec.upper()} {contract.pixel_format} "
        f"{contract.audio_codec.upper()} {contract.sample_rate}Hz "
        f"{contract.channel_layout}/{contract.channels}ch"
    )


def validate_selected_parts(
    candidates: Sequence[PartCandidate], config: AppConfig,
) -> tuple[SelectedPart, ...]:
    expected = expected_media_contract(config)
    selected: list[SelectedPart] = []
    for candidate in candidates:
        actual, duration = probe_media(candidate.path, config.ffprobe)
        if actual != expected:
            raise AutoEditorError(
                f"Part_{candidate.part:02d} media contract differs.\n\n"
                f"Expected:\n{_contract_text(expected)}\n\n"
                f"Actual:\n{_contract_text(actual)}\n\n"
                "No silent normalization or re-encoding was performed."
            )
        selected.append(SelectedPart(
            part=candidate.part,
            version=candidate.version,
            path=candidate.path,
            duration=duration,
            contract=actual,
        ))
    return tuple(selected)


def _final_pattern(topic_slug: str, language: str) -> re.Pattern[str]:
    prefix = f"{topic_slug}_FINAL_{language.upper()}"
    return re.compile(re.escape(prefix) + r"_([0-9]+)\.mp4\Z")


def next_final_path(output_root: Path, topic_slug: str, language: str) -> Path:
    directory = output_root / f"{topic_slug}_FINAL" / language.upper()
    pattern = _final_pattern(topic_slug, language)
    versions = []
    if directory.is_dir():
        versions = [
            int(match.group(1))
            for path in directory.iterdir()
            if path.is_file() and (match := pattern.fullmatch(path.name)) is not None
        ]
    version = max(versions, default=0) + 1
    prefix = f"{topic_slug}_FINAL_{language.upper()}"
    return directory / f"{prefix}_{version}.mp4"


def reserve_final_output(
    output_root: Path, topic_slug: str, language: str,
) -> FinalReservation:
    for _ in range(RESERVATION_ATTEMPTS):
        final_path = next_final_path(output_root, topic_slug, language)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(final_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        os.close(descriptor)
        version = int(_final_pattern(topic_slug, language).fullmatch(final_path.name).group(1))
        stem = final_path.stem
        reservation = FinalReservation(
            final_path=final_path,
            temporary_path=final_path.parent / f".{stem}.building.mp4",
            manifest_path=final_path.with_suffix(".json"),
            temporary_manifest_path=final_path.parent / f".{stem}.building.json",
            concat_path=final_path.parent / f".{stem}.concat.txt",
            version=version,
        )
        try:
            manifest_descriptor = os.open(
                reservation.manifest_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
            )
        except FileExistsError as exc:
            final_path.unlink()
            raise AutoEditorError(
                f"Manifest FINAL đã tồn tại mà không có video tương ứng: "
                f"{reservation.manifest_path}"
            ) from exc
        except OSError:
            final_path.unlink()
            raise
        os.close(manifest_descriptor)
        return reservation
    raise AutoEditorError("Không thể reserve FINAL output do quá nhiều build đồng thời.")


def _duration_tolerance(part_count: int, fps: Fraction) -> float:
    return max(0.25, part_count / float(fps) + 0.1)


def validate_final_candidate(
    path: Path,
    expected_contract: MediaContract,
    expected_duration: float,
    part_count: int,
    ffprobe: str,
) -> float:
    actual_contract, actual_duration = probe_media(path, ffprobe)
    if actual_contract != expected_contract:
        raise AutoEditorError(
            "FINAL candidate media contract differs after concat.\n"
            f"Expected: {_contract_text(expected_contract)}\n"
            f"Actual: {_contract_text(actual_contract)}"
        )
    tolerance = _duration_tolerance(part_count, expected_contract.fps)
    difference = abs(actual_duration - expected_duration)
    if difference > tolerance:
        raise AutoEditorError(
            "FINAL duration validation failed.\n"
            f"Expected sum: {expected_duration:.3f}s\n"
            f"Actual: {actual_duration:.3f}s\n"
            f"Tolerance: {tolerance:.3f}s"
        )
    return actual_duration


def _write_manifest(
    destination: Path,
    manifest: TopicManifest,
    language: str,
    parts: Sequence[SelectedPart],
    output_name: str,
    output_version: int,
    duration: float,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "topic": manifest.topic,
        "language": language,
        "production": language == "en",
        "expected_parts": manifest.expected_parts,
        "parts": [
            {
                "part": part.part,
                "version": part.version,
                "source": part.path.name,
                "duration": part.duration,
            }
            for part in parts
        ],
        "output": output_name,
        "version": output_version,
        "duration": duration,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def _cleanup_reservation(reservation: FinalReservation, *, remove_final: bool) -> None:
    for path in (
        reservation.temporary_path,
        reservation.temporary_manifest_path,
        reservation.concat_path,
    ):
        if path.is_file():
            path.unlink()
    if remove_final and reservation.final_path.is_file():
        reservation.final_path.unlink()
    if remove_final and reservation.manifest_path.is_file():
        reservation.manifest_path.unlink()


def publish_assembly(
    plan: AssemblyPlan, config: AppConfig, output_root: Path,
) -> tuple[Path, Path, dict[str, Any]]:
    reservation = reserve_final_output(output_root, plan.topic_slug, plan.language)
    published_video = False
    try:
        _cleanup_reservation(reservation, remove_final=False)
        write_concat_file(
            [part.path for part in plan.selected_parts], reservation.concat_path
        )
        command = [
            config.ffmpeg,
            "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(reservation.concat_path),
            "-map", "0:v:0", "-map", "0:a:0",
            "-c", "copy", "-movflags", "+faststart",
            str(reservation.temporary_path),
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
        except OSError as exc:
            raise AutoEditorError(f"Không chạy được FFmpeg FINAL concat: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise AutoEditorError(f"FFmpeg FINAL concat thất bại:\n{detail[-3000:]}")
        duration = validate_final_candidate(
            reservation.temporary_path,
            plan.selected_parts[0].contract,
            plan.expected_duration,
            len(plan.selected_parts),
            config.ffprobe,
        )
        payload = _write_manifest(
            reservation.temporary_manifest_path,
            plan.manifest,
            plan.language,
            plan.selected_parts,
            reservation.final_path.name,
            reservation.version,
            duration,
        )
        if (
            not reservation.final_path.is_file()
            or reservation.final_path.stat().st_size != 0
            or not reservation.manifest_path.is_file()
            or reservation.manifest_path.stat().st_size != 0
        ):
            raise AutoEditorError("FINAL video/manifest reservation không còn thuộc build hiện tại.")
        os.replace(reservation.temporary_path, reservation.final_path)
        published_video = True
        os.replace(reservation.temporary_manifest_path, reservation.manifest_path)
        return reservation.final_path, reservation.manifest_path, payload
    except BaseException:
        if published_video and reservation.final_path.is_file():
            reservation.final_path.unlink()
        _cleanup_reservation(reservation, remove_final=True)
        raise
    finally:
        if reservation.concat_path.is_file():
            reservation.concat_path.unlink()


def create_plan(
    topic_manifest_path: Path,
    config: AppConfig,
    output_root: Path,
    language: str | None = None,
) -> AssemblyPlan:
    manifest = load_topic_manifest(topic_manifest_path)
    selected_language = language or manifest.production_language
    if selected_language not in SUPPORTED_LANGUAGES:
        raise AutoEditorError("Language assembler chỉ hỗ trợ EN hoặc VI.")
    require_executable(config.ffmpeg, "ffmpeg")
    require_executable(config.ffprobe, "ffprobe")
    candidates = discover_latest_parts(manifest, output_root, selected_language)
    selected = validate_selected_parts(candidates, config)
    topic_slug = safe_topic_slug(manifest.topic)
    return AssemblyPlan(
        manifest=manifest,
        language=selected_language,
        topic_slug=topic_slug,
        selected_parts=selected,
        expected_duration=sum(part.duration for part in selected),
        planned_output=next_final_path(output_root, topic_slug, selected_language),
    )


def display_plan(plan: AssemblyPlan) -> None:
    if plan.language == "vi":
        print("EXPERIMENTAL PIPELINE")
        print("LANGUAGE: VI\n")
    print("===============================================")
    print("YTB02 AUTOEDITOR - FINAL ENGLISH ASSEMBLY" if plan.language == "en" else
          "YTB02 AUTOEDITOR - FINAL VI ASSEMBLY (EXPERIMENTAL)")
    print("===============================================")
    print(f"\nTOPIC:\n{plan.manifest.topic}")
    label = "PRODUCTION LANGUAGE" if plan.language == "en" else "EXPERIMENTAL LANGUAGE"
    print(f"\n{label}:\n{plan.language.upper()}")
    print(f"\nEXPECTED PARTS:\n{plan.manifest.expected_parts}")
    print("\nSELECTED SOURCES:")
    for part in plan.selected_parts:
        print(f"\nPART {part.part:02d}")
        print(f"Version: {part.version}")
        print(part.path.name)
    print("\nSOURCE DURATIONS:")
    for part in plan.selected_parts:
        print(f"Part {part.part:02d}: {part.duration:.3f}s")
    print(f"\nEXPECTED FINAL DURATION:\n{plan.expected_duration:.3f}s")
    print(f"\nPLANNED FINAL VIDEO:\n{plan.planned_output.resolve()}")


def run_final_assembly(
    topic_manifest_path: Path,
    config_path: Path,
    output_root: Path,
    *,
    language: str | None = None,
    dry_run: bool = False,
) -> tuple[Path, Path] | None:
    config = load_config(config_path)
    plan = create_plan(topic_manifest_path, config, output_root, language)
    display_plan(plan)
    if dry_run:
        print("\nDRY RUN OK - no FINAL MP4 or manifest was created.")
        return None
    print("\nBuilding final video with FFmpeg stream copy...")
    final_path, manifest_path, _ = publish_assembly(plan, config, output_root)
    print(f"\nFINAL VIDEO:\n{final_path.resolve()}")
    print(f"\nFINAL MANIFEST:\n{manifest_path.resolve()}")
    print("\n===============================================")
    print("BUILD SUCCESS")
    print("===============================================")
    return final_path, manifest_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assemble the latest valid Part versions into one FINAL video"
    )
    parser.add_argument(
        "--manifest", type=Path, default=PROJECT_ROOT / "input" / "topic.json"
    )
    parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "config.json"
    )
    parser.add_argument(
        "--output-root", type=Path, default=PROJECT_ROOT / "output"
    )
    parser.add_argument("--language", choices=("en", "vi"))
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    args = _parser().parse_args(argv)
    try:
        run_final_assembly(
            args.manifest.resolve(),
            args.config.resolve(),
            args.output_root.resolve(),
            language=args.language,
            dry_run=args.dry_run,
        )
        return 0
    except AutoEditorError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nĐã hủy theo yêu cầu người dùng.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
