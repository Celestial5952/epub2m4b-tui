from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from epub2m4b.audio.m4b import assemble_m4b
from epub2m4b.epub.cover import CoverImage
from epub2m4b.exceptions import AudioValidationError, ExternalToolError
from epub2m4b.models import (
    Chunk,
    ChunkStatus,
    JobManifest,
    JobStatus,
    ManifestBook,
    ManifestSource,
    NarrationSettings,
)


def _manifest(tmp_path: Path) -> JobManifest:
    settings = NarrationSettings("fake", "model", "voice", 1.0, "Read")
    chunks = []
    for chapter, chunk_index, duration in [(0, 0, 1.25), (0, 1, 0.75), (2, 0, 2.5)]:
        chunk = Chunk.create(
            chapter_index=chapter,
            chunk_index=chunk_index,
            text=f"Text {chapter}-{chunk_index}",
            settings=settings,
        )
        audio = tmp_path / f"{chapter}-{chunk_index}.wav"
        audio.write_bytes(b"audio")
        chunks.append(
            replace(
                chunk,
                status=ChunkStatus.COMPLETE,
                audio_path=str(audio),
                duration_seconds=duration,
            )
        )
    return JobManifest(
        "job",
        "0.1.0",
        ManifestSource("book.epub", "hash"),
        ManifestBook("A # Title", ("One", "Two")),
        settings,
        tuple(chunks),
        status=JobStatus.COMPLETE,
    )


class _Runner:
    def __init__(
        self,
        *,
        fail_ffmpeg: bool = False,
        chapter_count: int = 2,
        omit_cover_stream: bool = False,
    ) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []
        self.fail_ffmpeg = fail_ffmpeg
        self.chapter_count = chapter_count
        self.omit_cover_stream = omit_cover_stream
        self.metadata_text = ""
        self.concat_text = ""
        self.cover_bytes: bytes | None = None
        self.cover_mode: int | None = None
        self.cover_requested = False

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append((command, kwargs))
        if command[0] == "/tools/ffmpeg":
            first_input = command.index("-i")
            self.concat_text = Path(command[first_input + 1]).read_text(encoding="utf-8")
            second_input = command.index("-i", command.index("-i") + 1)
            self.metadata_text = Path(command[second_input + 1]).read_text(encoding="utf-8")
            self.cover_requested = "-disposition:v:0" in command
            if self.cover_requested:
                third_input = command.index("-i", second_input + 1)
                cover_path = Path(command[third_input + 1])
                self.cover_bytes = cover_path.read_bytes()
                self.cover_mode = cover_path.stat().st_mode & 0o777
            if not self.fail_ffmpeg:
                Path(command[-1]).write_bytes(b"m4b")
            return subprocess.CompletedProcess(command, 1 if self.fail_ffmpeg else 0, "", "private")
        chapters = [
            {"start_time": "0.000", "end_time": "2.000", "tags": {"title": "Start"}},
            {"start_time": "2.000", "end_time": "4.500", "tags": {"title": "End"}},
        ][: self.chapter_count]
        streams: list[dict[str, object]] = [
            {"codec_type": "audio", "codec_name": "aac", "disposition": {"attached_pic": 0}}
        ]
        if self.cover_requested and not self.omit_cover_stream:
            streams.append(
                {
                    "codec_type": "video",
                    "codec_name": "mjpeg",
                    "disposition": {"attached_pic": 1},
                }
            )
        payload = json.dumps(
            {"format": {"duration": "4.500"}, "chapters": chapters, "streams": streams}
        )
        return subprocess.CompletedProcess(command, 0, payload, "")


def _resolve(name: str) -> str:
    return f"/tools/{name}"


def test_assemble_uses_safe_command_chapters_and_atomic_result(tmp_path: Path) -> None:
    runner = _Runner()
    output = tmp_path / "out" / "book.m4b"

    result = assemble_m4b(
        _manifest(tmp_path),
        {0: "Opening; #1", 2: "Finale"},
        output,
        runner=runner,
        resolver=_resolve,
    )

    assert output.read_bytes() == b"m4b"
    assert result.duration_seconds == 4.5
    assert [(mark.start_ms, mark.end_ms) for mark in result.chapters] == [(0, 2000), (2000, 4500)]
    ffmpeg, kwargs = runner.calls[0]
    assert ffmpeg[0] == "/tools/ffmpeg"
    assert kwargs["shell"] is False
    assert "-map_chapters" in ffmpeg
    assert "96k" in ffmpeg
    metadata = runner.metadata_text
    assert "title=A \\# Title" in metadata
    assert "album=A \\# Title" in metadata
    assert "artist=One, Two" in metadata
    assert "album_artist=One, Two" in metadata
    assert "genre=Audiobook" in metadata
    assert "title=Opening\\; \\#1" in metadata
    assert "START=2000\nEND=4500" in metadata
    probe, probe_kwargs = runner.calls[1]
    assert probe[0] == "/tools/ffprobe"
    assert probe_kwargs["shell"] is False


def test_ffmpeg_failure_preserves_existing_destination(tmp_path: Path) -> None:
    output = tmp_path / "book.m4b"
    output.write_bytes(b"existing")

    with pytest.raises(ExternalToolError, match="FFmpeg"):
        assemble_m4b(
            _manifest(tmp_path),
            {0: "One", 2: "Two"},
            output,
            runner=_Runner(fail_ffmpeg=True),
            resolver=_resolve,
        )

    assert output.read_bytes() == b"existing"
    assert not list(tmp_path.glob(".book.m4b.*"))


def test_validation_failure_preserves_existing_destination(tmp_path: Path) -> None:
    output = tmp_path / "book.m4b"
    output.write_bytes(b"existing")

    with pytest.raises(AudioValidationError, match="chapter count"):
        assemble_m4b(
            _manifest(tmp_path),
            {0: "One", 2: "Two"},
            output,
            runner=_Runner(chapter_count=1),
            resolver=_resolve,
        )

    assert output.read_bytes() == b"existing"


def test_rejects_incomplete_manifest_and_bad_audio(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    with pytest.raises(AudioValidationError, match="job must be complete"):
        assemble_m4b(
            replace(manifest, status=JobStatus.RUNNING),
            {},
            tmp_path / "book.m4b",
            resolver=_resolve,
        )

    Path(manifest.chunks[0].audio_path or "").unlink()
    with pytest.raises(AudioValidationError, match="missing"):
        assemble_m4b(manifest, {}, tmp_path / "book.m4b", resolver=_resolve)


def test_rejects_duplicate_chunks_and_missing_tools(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    duplicate = replace(manifest, chunks=manifest.chunks + (manifest.chunks[0],))
    with pytest.raises(AudioValidationError, match="duplicate"):
        assemble_m4b(duplicate, {}, tmp_path / "book.m4b", resolver=_resolve)

    with pytest.raises(ExternalToolError, match="available"):
        assemble_m4b(manifest, {}, tmp_path / "book.m4b", resolver=lambda _: None)


def test_rejects_invalid_bitrate(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        assemble_m4b(_manifest(tmp_path), {}, tmp_path / "book.m4b", bitrate_kbps=0)


def test_relative_cache_paths_are_absolute_in_concat_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(tmp_path)
    monkeypatch.chdir(tmp_path)
    relative_chunks = tuple(
        replace(chunk, audio_path=Path(chunk.audio_path or "").name)
        for chunk in manifest.chunks
    )
    runner = _Runner()

    assemble_m4b(
        replace(manifest, chunks=relative_chunks),
        {0: "One", 2: "Two"},
        tmp_path / "book.m4b",
        runner=runner,
        resolver=_resolve,
    )

    assert f"file '{tmp_path / '0-0.wav'}'" in runner.concat_text


def test_embeds_private_cover_and_requires_attached_picture(tmp_path: Path) -> None:
    runner = _Runner()
    cover = CoverImage("image/jpeg", ".jpg", b"jpeg cover")

    assemble_m4b(
        _manifest(tmp_path),
        {0: "One", 2: "Two"},
        tmp_path / "book.m4b",
        cover=cover,
        runner=runner,
        resolver=_resolve,
    )

    ffmpeg = runner.calls[0][0]
    assert ffmpeg[ffmpeg.index("-map", ffmpeg.index("-map") + 1) + 1] == "2:v:0"
    assert ffmpeg[ffmpeg.index("-c:v") + 1] == "mjpeg"
    assert ffmpeg[ffmpeg.index("-pix_fmt") + 1] == "yuvj420p"
    assert ffmpeg[ffmpeg.index("-disposition:v:0") + 1] == "attached_pic"
    assert runner.cover_bytes == b"jpeg cover"
    assert runner.cover_mode == 0o600


@pytest.mark.parametrize(
    ("media_type", "suffix", "expected_codec"),
    [
        ("image/png", ".png", "png"),
        ("image/webp", ".webp", "libwebp"),
    ],
)
def test_embeds_png_and_webp_covers_with_correct_codecs(
    tmp_path: Path, media_type: str, suffix: str, expected_codec: str
) -> None:
    runner = _Runner()
    cover = CoverImage(media_type, suffix, b"image-payload")

    assemble_m4b(
        _manifest(tmp_path),
        {0: "One", 2: "Two"},
        tmp_path / "book.m4b",
        cover=cover,
        runner=runner,
        resolver=_resolve,
    )

    ffmpeg = runner.calls[0][0]
    assert ffmpeg[ffmpeg.index("-c:v") + 1] == expected_codec
    assert "-pix_fmt" not in ffmpeg
    assert ffmpeg[ffmpeg.index("-disposition:v:0") + 1] == "attached_pic"
    assert runner.cover_bytes == b"image-payload"


def test_cover_validation_preserves_existing_destination(tmp_path: Path) -> None:
    output = tmp_path / "book.m4b"
    output.write_bytes(b"existing")

    with pytest.raises(AudioValidationError, match="attached cover"):
        assemble_m4b(
            _manifest(tmp_path),
            {},
            output,
            cover=CoverImage("image/png", ".png", b"png cover"),
            runner=_Runner(omit_cover_stream=True),
            resolver=_resolve,
        )

    assert output.read_bytes() == b"existing"


@pytest.mark.parametrize(
    "cover",
    [
        CoverImage("image/gif", ".gif", b"gif"),
        CoverImage("image/jpeg", ".png", b"jpeg"),
        CoverImage("image/jpeg", ".jpg", b""),
    ],
)
def test_rejects_invalid_cover_before_ffmpeg(tmp_path: Path, cover: CoverImage) -> None:
    with pytest.raises(ValueError, match="cover"):
        assemble_m4b(
            _manifest(tmp_path),
            {},
            tmp_path / "book.m4b",
            cover=cover,
            runner=_Runner(),
            resolver=_resolve,
        )
