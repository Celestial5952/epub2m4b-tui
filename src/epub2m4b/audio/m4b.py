"""Atomic FFmpeg assembly of chaptered M4B audiobooks."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from epub2m4b.audio.tools import write_concat_list
from epub2m4b.epub.cover import CoverImage
from epub2m4b.exceptions import AudioValidationError, ExternalToolError
from epub2m4b.models import ChunkStatus, JobManifest, JobStatus

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
ToolResolver = Callable[[str], str | None]


@dataclass(frozen=True, slots=True)
class ChapterMark:
    index: int
    title: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class AssemblyResult:
    path: Path
    duration_seconds: float
    size_bytes: int
    chapters: tuple[ChapterMark, ...]


def _metadata_value(value: str) -> str:
    single_line = " ".join(value.splitlines()).strip()
    return "".join(
        f"\\{character}" if character in "\\=;#" else character for character in single_line
    )


def _chapter_marks(manifest: JobManifest, titles: Mapping[int, str]) -> tuple[ChapterMark, ...]:
    ordered = sorted(manifest.chunks, key=lambda chunk: (chunk.chapter_index, chunk.chunk_index))
    seen: set[tuple[int, int]] = set()
    duration_by_chapter: dict[int, float] = {}
    for chunk in ordered:
        identity = (chunk.chapter_index, chunk.chunk_index)
        if identity in seen:
            raise AudioValidationError("manifest contains duplicate chunk indexes")
        seen.add(identity)
        if chunk.status is not ChunkStatus.COMPLETE:
            raise AudioValidationError("all chunks must be complete before M4B assembly")
        duration = chunk.duration_seconds
        if duration is None or not math.isfinite(duration) or duration <= 0:
            raise AudioValidationError("chunk duration must be finite and positive")
        duration_by_chapter[chunk.chapter_index] = (
            duration_by_chapter.get(chunk.chapter_index, 0.0) + duration
        )

    marks: list[ChapterMark] = []
    elapsed = 0.0
    for chapter_index in sorted(duration_by_chapter):
        start = round(elapsed * 1000)
        elapsed += duration_by_chapter[chapter_index]
        end = round(elapsed * 1000)
        if end <= start:
            raise AudioValidationError("chapter duration is too short")
        title = titles.get(chapter_index, "").strip() or f"Chapter {chapter_index + 1}"
        marks.append(ChapterMark(chapter_index, title, start, end))
    if not marks:
        raise AudioValidationError("manifest contains no narrated chapters")
    return tuple(marks)


def _write_ffmetadata(path: Path, manifest: JobManifest, chapters: tuple[ChapterMark, ...]) -> None:
    authors = ", ".join(manifest.book.authors)
    title = _metadata_value(manifest.book.title)
    lines = [";FFMETADATA1", f"title={title}", f"album={title}", "genre=Audiobook"]
    if authors:
        escaped_authors = _metadata_value(authors)
        lines.extend((f"artist={escaped_authors}", f"album_artist={escaped_authors}"))
    for chapter in chapters:
        lines.extend(
            [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={chapter.start_ms}",
                f"END={chapter.end_ms}",
                f"title={_metadata_value(chapter.title)}",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _audio_paths(manifest: JobManifest) -> tuple[Path, ...]:
    if manifest.status is not JobStatus.COMPLETE:
        raise AudioValidationError("job must be complete before M4B assembly")
    ordered = sorted(manifest.chunks, key=lambda chunk: (chunk.chapter_index, chunk.chunk_index))
    paths: list[Path] = []
    for chunk in ordered:
        if not chunk.audio_path:
            raise AudioValidationError("completed chunk is missing its audio path")
        path = Path(chunk.audio_path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
            raise AudioValidationError("chunk audio is missing, empty, or symlinked")
        # FFmpeg resolves concat-demuxer entries relative to the concat file,
        # which lives in a private temporary directory. Persisted cache paths
        # may be relative to the application working directory, so make their
        # meaning explicit before writing the list.
        paths.append(path.absolute())
    if not paths:
        raise AudioValidationError("manifest contains no audio chunks")
    return tuple(paths)


def _run_tool(
    command: list[str],
    *,
    runner: CommandRunner,
    failure_message: str,
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ExternalToolError(failure_message) from exc
    if result.returncode != 0:
        raise ExternalToolError(failure_message)
    return result


def _validate_output(
    path: Path,
    chapters: tuple[ChapterMark, ...],
    expected_duration: float,
    expect_cover: bool,
    *,
    ffprobe: str,
    runner: CommandRunner,
) -> float:
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
        raise AudioValidationError("FFmpeg did not create a usable M4B")
    result = _run_tool(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            (
                "format=duration:chapter=start_time,end_time:chapter_tags=title:"
                "stream=codec_type,codec_name:stream_disposition=attached_pic"
            ),
            "-of",
            "json",
            str(path),
        ],
        runner=runner,
        failure_message="FFprobe could not validate the assembled M4B",
    )
    try:
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
        probed_chapters = data["chapters"]
        streams = data.get("streams", [])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AudioValidationError("FFprobe returned invalid M4B metadata") from exc
    tolerance = max(2.0, expected_duration * 0.005)
    if (
        not math.isfinite(duration)
        or duration <= 0
        or abs(duration - expected_duration) > tolerance
    ):
        raise AudioValidationError("assembled M4B duration does not match its chunks")
    if not isinstance(probed_chapters, list) or len(probed_chapters) != len(chapters):
        raise AudioValidationError("assembled M4B chapter count is incorrect")
    for expected, actual in zip(chapters, probed_chapters, strict=True):
        try:
            start_ms = round(float(actual["start_time"]) * 1000)
            end_ms = round(float(actual["end_time"]) * 1000)
        except (KeyError, TypeError, ValueError) as exc:
            raise AudioValidationError("assembled M4B chapter timing is invalid") from exc
        # AAC frames contain 1024 samples (~23.2ms at 44.1kHz). MP4 chapter
        # atoms snap to packet boundaries, so allow up to 50ms tolerance.
        if abs(start_ms - expected.start_ms) > 50 or abs(end_ms - expected.end_ms) > 50:
            raise AudioValidationError("assembled M4B chapter timing is incorrect")
    if expect_cover and (
        not isinstance(streams, list)
        or not any(
            isinstance(stream, dict)
            and stream.get("codec_type") == "video"
            and isinstance(stream.get("disposition"), dict)
            and stream["disposition"].get("attached_pic") == 1
            for stream in streams
        )
    ):
        raise AudioValidationError("assembled M4B is missing its attached cover")
    return duration


def _write_cover(path: Path, cover: CoverImage) -> Path:
    suffix_by_type = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    if not isinstance(cover, CoverImage):
        raise ValueError("cover must be a CoverImage")
    suffix = suffix_by_type.get(cover.media_type)
    if suffix is None or cover.suffix != suffix:
        raise ValueError("cover media type and suffix must be supported and consistent")
    if not isinstance(cover.data, bytes) or not cover.data:
        raise ValueError("cover data must be non-empty bytes")
    cover_path = path / f"cover{suffix}"
    cover_path.write_bytes(cover.data)
    cover_path.chmod(0o600)
    return cover_path


def assemble_m4b(
    manifest: JobManifest,
    chapter_titles: Mapping[int, str],
    destination: str | os.PathLike[str],
    *,
    bitrate_kbps: int = 96,
    cover: CoverImage | None = None,
    runner: CommandRunner | None = None,
    resolver: ToolResolver | None = None,
) -> AssemblyResult:
    """Assemble and validate an M4B, then atomically publish it."""

    if isinstance(bitrate_kbps, bool) or not isinstance(bitrate_kbps, int) or bitrate_kbps <= 0:
        raise ValueError("bitrate must be a positive integer")
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    paths = _audio_paths(manifest)
    chapters = _chapter_marks(manifest, chapter_titles)
    expected_duration = chapters[-1].end_ms / 1000
    resolve = resolver or shutil.which
    ffmpeg = resolve("ffmpeg")
    ffprobe = resolve("ffprobe")
    if not ffmpeg or not ffprobe:
        raise ExternalToolError("FFmpeg and FFprobe must both be available on PATH")
    invoke = runner or subprocess.run

    with tempfile.TemporaryDirectory(prefix=f".{target.name}.", dir=target.parent) as work:
        work_path = Path(work)
        concat_path = work_path / "concat.txt"
        metadata_path = work_path / "metadata.txt"
        partial = work_path / "output.m4b"
        write_concat_list(paths, concat_path)
        _write_ffmetadata(metadata_path, manifest, chapters)
        cover_path = _write_cover(work_path, cover) if cover is not None else None
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-i",
            str(metadata_path),
        ]
        if cover_path is not None:
            command.extend(("-i", str(cover_path)))
        command.extend(
            (
                "-map",
                "0:a:0",
                "-map_metadata",
                "1",
                "-map_chapters",
                "1",
            )
        )
        if cover_path is not None and cover is not None:
            vcodec = (
                "png"
                if cover.media_type == "image/png"
                else ("libwebp" if cover.media_type == "image/webp" else "mjpeg")
            )
            command.extend(
                (
                    "-map",
                    "2:v:0",
                    "-c:v",
                    vcodec,
                    "-disposition:v:0",
                    "attached_pic",
                )
            )
            if vcodec == "mjpeg":
                command.extend(("-pix_fmt", "yuvj420p"))
        command.extend(
            (
                "-c:a",
                "aac",
                "-b:a",
                f"{bitrate_kbps}k",
                "-movflags",
                "+faststart",
                str(partial),
            )
        )
        _run_tool(
            command,
            runner=invoke,
            failure_message="FFmpeg could not assemble the M4B",
        )
        duration = _validate_output(
            partial,
            chapters,
            expected_duration,
            cover_path is not None,
            ffprobe=ffprobe,
            runner=invoke,
        )
        size = partial.stat().st_size
        os.replace(partial, target)
    return AssemblyResult(target, duration, size, chapters)
