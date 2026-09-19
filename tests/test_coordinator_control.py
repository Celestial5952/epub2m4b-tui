from __future__ import annotations

import asyncio
import wave
from pathlib import Path

import pytest

from epub2m4b.exceptions import GenerationError
from epub2m4b.generation.cache import AudioCache
from epub2m4b.generation.coordinator import GenerationCoordinator
from epub2m4b.generation.manifest import ManifestRepository
from epub2m4b.models import (
    Chunk,
    JobManifest,
    JobStatus,
    ManifestBook,
    ManifestSource,
    NarrationSettings,
)
from epub2m4b.providers.base import SynthesisRequest, SynthesisResult


class SignallingProvider:
    name = "control-test"

    def __init__(self, signal) -> None:
        self.signal = signal
        self.requests: list[SynthesisRequest] = []

    async def synthesize(self, request: SynthesisRequest, destination: Path) -> SynthesisResult:
        self.requests.append(request)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(destination), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"\0\0" * 800)
        if len(self.requests) == 1:
            self.signal()
        return SynthesisResult(request.request_id, 0.1, destination.stat().st_size, "control")


def _manifest(status: JobStatus = JobStatus.READY) -> JobManifest:
    settings = NarrationSettings("control-test", "model", "voice", 1.0, "")
    chunks = tuple(
        Chunk.create(chapter_index=0, chunk_index=i, text=f"chunk {i}", settings=settings)
        for i in range(2)
    )
    return JobManifest(
        job_id="control-job",
        app_version="test",
        source=ManifestSource("book.epub", "a" * 64),
        book=ManifestBook("Book", ("Author",)),
        narration=settings,
        chunks=chunks,
        status=status,
    )


def _setup(tmp_path: Path, status: JobStatus = JobStatus.READY):
    path = tmp_path / "manifest.json"
    ManifestRepository.save(path, _manifest(status))
    return path


def _coordinator(tmp_path: Path, provider: SignallingProvider) -> GenerationCoordinator:
    return GenerationCoordinator(
        provider,
        AudioCache(tmp_path / "cache"),
        validator=lambda p: p.is_file() and p.stat().st_size > 0,
        duration_reader=lambda p: 0.1,
    )


def test_pause_after_first_commit_resumes_remaining(tmp_path: Path) -> None:
    holder: dict[str, GenerationCoordinator] = {}
    provider = SignallingProvider(lambda: holder["coordinator"].request_pause())
    holder["coordinator"] = _coordinator(tmp_path, provider)
    path = _setup(tmp_path)
    paused = asyncio.run(holder["coordinator"].run(path))
    assert paused.manifest.status is JobStatus.PAUSED
    assert len(provider.requests) == 1

    resumed_provider = SignallingProvider(lambda: None)
    resumed = _coordinator(tmp_path, resumed_provider)
    result = asyncio.run(resumed.run(path))
    assert result.manifest.status is JobStatus.COMPLETE
    assert len(resumed_provider.requests) == 1


def test_cancel_after_first_commit_returns_cancelled(tmp_path: Path) -> None:
    holder: dict[str, GenerationCoordinator] = {}
    provider = SignallingProvider(lambda: holder["coordinator"].request_cancel())
    holder["coordinator"] = _coordinator(tmp_path, provider)
    result = asyncio.run(holder["coordinator"].run(_setup(tmp_path)))
    assert result.manifest.status is JobStatus.CANCELLED
    assert len(provider.requests) == 1


def test_cancel_wins_over_pause(tmp_path: Path) -> None:
    holder: dict[str, GenerationCoordinator] = {}
    provider = SignallingProvider(
        lambda: (holder["coordinator"].request_pause(), holder["coordinator"].request_cancel())
    )
    holder["coordinator"] = _coordinator(tmp_path, provider)
    result = asyncio.run(holder["coordinator"].run(_setup(tmp_path)))
    assert result.manifest.status is JobStatus.CANCELLED


@pytest.mark.parametrize("status", [JobStatus.CANCELLED])
def test_cancelled_manifest_raises_without_provider_call(tmp_path: Path, status: JobStatus) -> None:
    provider = SignallingProvider(lambda: None)
    coordinator = _coordinator(tmp_path, provider)
    with pytest.raises(GenerationError):
        asyncio.run(coordinator.run(_setup(tmp_path, status)))
    assert provider.requests == []


def test_complete_manifest_is_noop(tmp_path: Path) -> None:
    provider = SignallingProvider(lambda: None)
    coordinator = _coordinator(tmp_path, provider)
    path = _setup(tmp_path, JobStatus.COMPLETE)
    result = asyncio.run(coordinator.run(path))
    assert result.synthesized_chunks == 0
    assert result.recovered_chunks == 0
    assert provider.requests == []
