from __future__ import annotations

import asyncio
import wave
from dataclasses import replace
from pathlib import Path

import pytest

from epub2m4b.exceptions import GenerationError, ProviderError
from epub2m4b.generation.cache import AudioCache
from epub2m4b.generation.coordinator import GenerationCoordinator
from epub2m4b.generation.manifest import ManifestRepository
from epub2m4b.models import (
    Chunk,
    ChunkStatus,
    JobManifest,
    JobStatus,
    ManifestBook,
    ManifestSource,
    NarrationSettings,
)
from epub2m4b.providers.fake import FakeTTSProvider


def _manifest(*, attempt_count: int = 0) -> JobManifest:
    settings = NarrationSettings("fake", "offline", "test", 1.0, "Read clearly.")
    chunk = Chunk.create(chapter_index=0, chunk_index=0, text="Testing.", settings=settings)
    chunk = Chunk(
        chunk.chapter_index,
        chunk.chunk_index,
        chunk.text,
        chunk.text_hash,
        chunk.generation_hash,
        attempt_count=attempt_count,
    )
    return JobManifest(
        "job",
        "0.1.0",
        ManifestSource("book.epub", "abc"),
        ManifestBook("Book", ("Author",)),
        settings,
        (chunk,),
    )


def _valid_wav(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as audio:
            return audio.getnframes() > 0
    except (OSError, EOFError, wave.Error):
        return False


def _duration(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / audio.getframerate()


def _coordinator(provider: object, root: Path, *, max_attempts: int = 3) -> GenerationCoordinator:
    async def no_sleep(_: float) -> None:
        return None

    return GenerationCoordinator(
        provider,  # type: ignore[arg-type]
        AudioCache(root),
        validator=_valid_wav,
        duration_reader=_duration,
        max_attempts=max_attempts,
        now=lambda: "2026-01-01T00:00:00+00:00",
        sleep=no_sleep,
    )


def test_generates_commits_and_persists_chunk(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    ManifestRepository.save(manifest_path, _manifest())
    provider = FakeTTSProvider()

    result = asyncio.run(_coordinator(provider, tmp_path / "cache").run(manifest_path))

    assert result.synthesized_chunks == 1
    assert result.recovered_chunks == 0
    assert result.manifest.status is JobStatus.COMPLETE
    chunk = result.manifest.chunks[0]
    assert chunk.status is ChunkStatus.COMPLETE
    assert chunk.attempt_count == 1
    assert chunk.audio_path and Path(chunk.audio_path).is_file()
    assert chunk.duration_seconds and chunk.duration_seconds > 0
    assert len(provider.requests) == 1
    assert ManifestRepository.load(manifest_path) == result.manifest


def test_valid_final_cache_recovers_without_provider_call(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    ManifestRepository.save(manifest_path, manifest)
    cache = AudioCache(tmp_path / "cache")
    final = cache.path_for(manifest.chunks[0])
    asyncio.run(FakeTTSProvider().synthesize(_request(manifest.chunks[0]), final))
    provider = FakeTTSProvider()

    result = asyncio.run(_coordinator(provider, cache.root).run(manifest_path))

    assert result.recovered_chunks == 1
    assert provider.requests == []


def test_valid_partial_is_promoted_without_duplicate_request(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    ManifestRepository.save(manifest_path, manifest)
    cache = AudioCache(tmp_path / "cache")
    final = cache.path_for(manifest.chunks[0])
    partial = final.with_name(f"{final.stem}.partial.wav")
    asyncio.run(FakeTTSProvider().synthesize(_request(manifest.chunks[0]), partial))
    provider = FakeTTSProvider()

    result = asyncio.run(_coordinator(provider, cache.root).run(manifest_path))

    assert result.recovered_chunks == 1
    assert provider.requests == []
    assert final.is_file()
    assert not partial.exists()


def _request(chunk: Chunk):
    from epub2m4b.providers.base import SynthesisRequest

    return SynthesisRequest(chunk.text, "offline", "test", 1.0, "Read clearly.", chunk.id)


class _FailsOnce(FakeTTSProvider):
    def __init__(self, *, retryable: bool = True) -> None:
        super().__init__()
        self.calls = 0
        self.retryable = retryable

    async def synthesize(self, request, destination):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            raise ProviderError("safe provider failure", retryable=self.retryable)
        return await super().synthesize(request, destination)


def test_retryable_failure_is_bounded_and_then_succeeds(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    ManifestRepository.save(manifest_path, _manifest())
    provider = _FailsOnce()

    result = asyncio.run(_coordinator(provider, tmp_path / "cache").run(manifest_path))

    assert provider.calls == 2
    assert result.manifest.chunks[0].attempt_count == 2
    assert result.manifest.status is JobStatus.COMPLETE


def test_retryable_failure_waits_before_retry(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    ManifestRepository.save(manifest_path, _manifest())
    provider = _FailsOnce()
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    coordinator = GenerationCoordinator(
        provider,
        AudioCache(tmp_path / "cache"),
        validator=_valid_wav,
        duration_reader=_duration,
        sleep=record_sleep,
        retry_delay=lambda attempt: float(attempt * 3),
    )
    asyncio.run(coordinator.run(manifest_path))

    assert delays == [3.0]


def test_nonretryable_failure_persists_failed_state(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    ManifestRepository.save(manifest_path, _manifest())
    provider = _FailsOnce(retryable=False)

    with pytest.raises(GenerationError):
        asyncio.run(_coordinator(provider, tmp_path / "cache").run(manifest_path))

    saved = ManifestRepository.load(manifest_path)
    assert saved.status is JobStatus.FAILED
    assert saved.chunks[0].status is ChunkStatus.FAILED
    assert saved.chunks[0].attempt_count == 1
    assert provider.calls == 1


def test_exhausted_attempt_count_never_calls_provider(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    ManifestRepository.save(manifest_path, _manifest(attempt_count=3))
    provider = FakeTTSProvider()

    with pytest.raises(GenerationError, match="retry limit"):
        asyncio.run(_coordinator(provider, tmp_path / "cache").run(manifest_path))

    assert provider.requests == []
    assert ManifestRepository.load(manifest_path).status is JobStatus.FAILED


class _WritesThenFails(FakeTTSProvider):
    async def synthesize(self, request, destination):  # type: ignore[no-untyped-def]
        await super().synthesize(request, destination)
        raise ProviderError("connection closed after body", retryable=True)


def test_completed_partial_survives_transport_error_without_retry(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    ManifestRepository.save(manifest_path, _manifest())
    provider = _WritesThenFails()

    result = asyncio.run(_coordinator(provider, tmp_path / "cache").run(manifest_path))

    assert len(provider.requests) == 1
    assert result.recovered_chunks == 1
    assert result.manifest.status is JobStatus.COMPLETE


class _InvalidProvider:
    name = "fake"

    async def synthesize(self, request, destination):  # type: ignore[no-untyped-def]
        destination.write_bytes(b"not-wave")


def test_invalid_audio_is_not_promoted(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    ManifestRepository.save(manifest_path, manifest)
    cache = AudioCache(tmp_path / "cache")

    with pytest.raises(GenerationError, match="could not generate a chunk"):
        asyncio.run(_coordinator(_InvalidProvider(), cache.root).run(manifest_path))

    final = cache.path_for(manifest.chunks[0])
    assert not final.exists()
    saved = ManifestRepository.load(manifest_path)
    assert saved.status is JobStatus.FAILED
    assert saved.chunks[0].status is ChunkStatus.FAILED
    assert saved.chunks[0].attempt_count == 3
    assert "invalid WAV" in (saved.chunks[0].last_error or "")


def test_provider_mismatch_stops_before_manifest_or_cache_changes(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    ManifestRepository.save(manifest_path, manifest)
    original = manifest_path.read_bytes()

    class WrongProvider(FakeTTSProvider):
        name = "wrong"

    with pytest.raises(GenerationError, match="does not match"):
        asyncio.run(_coordinator(WrongProvider(), tmp_path / "cache").run(manifest_path))

    assert manifest_path.read_bytes() == original
    assert not (tmp_path / "cache").exists()


class _InvalidOnce(FakeTTSProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def synthesize(self, request, destination):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            destination.write_bytes(b"not-wave")
            return None
        return await super().synthesize(request, destination)


def test_invalid_audio_is_retried_and_can_succeed(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    ManifestRepository.save(manifest_path, _manifest())
    provider = _InvalidOnce()

    result = asyncio.run(_coordinator(provider, tmp_path / "cache").run(manifest_path))

    assert provider.calls == 2
    assert result.manifest.chunks[0].attempt_count == 2
    assert result.manifest.status is JobStatus.COMPLETE
    assert result.synthesized_chunks == 1


def test_resume_does_not_resave_or_inflate_already_complete_chunks(tmp_path: Path) -> None:
    manifest = _manifest()
    cache = AudioCache(tmp_path / "cache")
    final = cache.path_for(manifest.chunks[0])
    final.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(FakeTTSProvider().synthesize(_request(manifest.chunks[0]), final))

    completed_chunk = replace(
        manifest.chunks[0],
        status=ChunkStatus.COMPLETE,
        audio_path=str(final),
        duration_seconds=_duration(final),
    )
    complete_manifest = replace(manifest, chunks=(completed_chunk,), status=JobStatus.RUNNING)
    manifest_path = tmp_path / "manifest.json"
    ManifestRepository.save(manifest_path, complete_manifest)

    provider = FakeTTSProvider()
    result = asyncio.run(_coordinator(provider, cache.root).run(manifest_path))

    assert result.recovered_chunks == 0
    assert result.synthesized_chunks == 0
    assert result.manifest.status is JobStatus.COMPLETE

