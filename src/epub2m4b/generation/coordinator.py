"""Serial, crash-resumable narration generation."""

from __future__ import annotations

import asyncio
import math
import os
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from epub2m4b.exceptions import GenerationError, ProviderError
from epub2m4b.generation.cache import AudioCache
from epub2m4b.generation.manifest import ManifestRepository
from epub2m4b.models import Chunk, ChunkStatus, JobManifest, JobStatus
from epub2m4b.providers.base import SynthesisRequest, TTSProvider


@dataclass(frozen=True, slots=True)
class GenerationResult:
    manifest: JobManifest
    synthesized_chunks: int
    recovered_chunks: int


class GenerationCoordinator:
    """Generate only missing audio and persist every paid-work boundary."""

    def __init__(
        self,
        provider: TTSProvider,
        cache: AudioCache,
        *,
        validator: Callable[[Path], bool],
        duration_reader: Callable[[Path], float],
        max_attempts: int = 3,
        now: Callable[[], str] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        retry_delay: Callable[[int], float] | None = None,
        progress: Callable[[JobManifest], None] | None = None,
    ) -> None:
        if max_attempts <= 0:
            raise ValueError("max attempts must be greater than zero")
        self.provider = provider
        self.cache = cache
        self.validator = validator
        self.duration_reader = duration_reader
        self.max_attempts = max_attempts
        self.now = now or (lambda: datetime.now(UTC).isoformat())
        self.sleep = sleep
        self.retry_delay = retry_delay or (
            lambda attempt: min(30.0, float(2 ** max(0, attempt - 1)))
        )
        self.progress = progress
        self._pause_requested = False
        self._cancel_requested = False

    def request_pause(self) -> None:
        """Stop at the next durable chunk boundary and persist a paused job."""

        self._pause_requested = True

    def request_cancel(self) -> None:
        """Stop at the next durable chunk boundary and persist a cancelled job."""

        self._cancel_requested = True

    async def run(self, manifest_path: Path) -> GenerationResult:
        manifest_path = Path(manifest_path)
        manifest = ManifestRepository.load(manifest_path)
        if manifest.status is JobStatus.CANCELLED:
            raise GenerationError("cancelled jobs cannot be resumed")
        if manifest.status is JobStatus.COMPLETE:
            return GenerationResult(manifest, 0, 0)
        if manifest.narration.provider != self.provider.name:
            raise GenerationError("manifest narration provider does not match the active provider")
        self.cache.ensure()
        manifest = replace(manifest, status=JobStatus.RUNNING, updated_at=self.now())
        self._save(manifest_path, manifest)
        synthesized = 0
        recovered = 0

        for position in range(len(manifest.chunks)):
            stopped = self._stop_if_requested(manifest_path, manifest)
            if stopped is not None:
                return GenerationResult(stopped, synthesized, recovered)
            chunk = manifest.chunks[position]
            final_path = self.cache.path_for(chunk)
            final_path.parent.mkdir(parents=True, exist_ok=True)

            duration = self._validated_duration(final_path)
            if duration is not None:
                if chunk.status is not ChunkStatus.COMPLETE:
                    manifest = self._complete(manifest, position, final_path, duration)
                    self._save(manifest_path, manifest)
                    recovered += 1
                continue

            partial_path = self._partial_path(final_path)
            duration = self._promote_valid_partial(partial_path, final_path)
            if duration is not None:
                if chunk.status is not ChunkStatus.COMPLETE:
                    manifest = self._complete(manifest, position, final_path, duration)
                    self._save(manifest_path, manifest)
                    recovered += 1
                continue

            while chunk.attempt_count < self.max_attempts:
                stopped = self._stop_if_requested(manifest_path, manifest)
                if stopped is not None:
                    return GenerationResult(stopped, synthesized, recovered)
                chunk = replace(
                    chunk,
                    status=ChunkStatus.GENERATING,
                    attempt_count=chunk.attempt_count + 1,
                    last_error=None,
                )
                manifest = self._replace_chunk(manifest, position, chunk)
                self._save(manifest_path, manifest)
                self._remove_partial(partial_path)

                request = SynthesisRequest(
                    text=chunk.text,
                    model=manifest.narration.model,
                    voice=manifest.narration.voice,
                    speed=manifest.narration.speed,
                    instructions=manifest.narration.instructions,
                    request_id=chunk.id,
                    options=dict(manifest.narration.generation_options),
                )
                try:
                    await self.provider.synthesize(request, partial_path)
                    duration = self._validated_duration(partial_path)
                    if duration is None:
                        self._remove_partial(partial_path)
                        raise ProviderError("provider returned invalid WAV audio", retryable=True)
                    self._fsync_file(partial_path)
                    os.replace(partial_path, final_path)
                    self._fsync_directory(final_path.parent)
                except ProviderError as exc:
                    # A streaming response may finish writing before its client
                    # reports a transport error. Recover it before retrying.
                    duration = self._promote_valid_partial(partial_path, final_path)
                    if duration is not None:
                        manifest = self._complete(manifest, position, final_path, duration)
                        self._save(manifest_path, manifest)
                        recovered += 1
                        break
                    chunk = replace(chunk, status=ChunkStatus.FAILED, last_error=str(exc))
                    manifest = self._replace_chunk(manifest, position, chunk)
                    self._save(manifest_path, manifest)
                    if exc.retryable and chunk.attempt_count < self.max_attempts:
                        stopped = self._stop_if_requested(manifest_path, manifest)
                        if stopped is not None:
                            return GenerationResult(stopped, synthesized, recovered)
                        delay = self.retry_delay(chunk.attempt_count)
                        if not math.isfinite(delay) or delay < 0:
                            raise GenerationError(
                                "retry delay must be finite and non-negative"
                            ) from exc
                        await self.sleep(delay)
                        continue
                    self._fail_job(manifest_path, manifest)
                    raise GenerationError("narration provider could not generate a chunk") from exc
                except Exception as exc:
                    self._remove_partial(partial_path)
                    chunk = replace(
                        chunk,
                        status=ChunkStatus.FAILED,
                        last_error="generated audio did not pass validation",
                    )
                    manifest = self._replace_chunk(manifest, position, chunk)
                    self._fail_job(manifest_path, manifest)
                    if isinstance(exc, GenerationError):
                        raise
                    raise GenerationError("generated audio could not be committed") from exc
                else:
                    chunk = replace(
                        chunk,
                        status=ChunkStatus.COMPLETE,
                        audio_path=str(final_path),
                        duration_seconds=duration,
                        generated_at=self.now(),
                        last_error=None,
                    )
                    manifest = self._replace_chunk(manifest, position, chunk)
                    self._save(manifest_path, manifest)
                    synthesized += 1
                    break
            else:
                self._fail_job(manifest_path, manifest)
                raise GenerationError("chunk retry limit was already reached")

        stopped = self._stop_if_requested(manifest_path, manifest)
        if stopped is not None:
            return GenerationResult(stopped, synthesized, recovered)
        manifest = replace(manifest, status=JobStatus.COMPLETE, updated_at=self.now())
        self._save(manifest_path, manifest)
        return GenerationResult(manifest, synthesized, recovered)

    def _stop_if_requested(
        self,
        path: Path,
        manifest: JobManifest,
    ) -> JobManifest | None:
        status = (
            JobStatus.CANCELLED
            if self._cancel_requested
            else JobStatus.PAUSED
            if self._pause_requested
            else None
        )
        if status is None:
            return None
        stopped = replace(manifest, status=status, updated_at=self.now())
        self._save(path, stopped)
        return stopped

    def _save(self, path: Path, manifest: JobManifest) -> None:
        ManifestRepository.save(path, manifest)
        if self.progress is not None:
            # Status rendering is observational and must never compromise a
            # durable paid-work boundary.
            with suppress(Exception):
                self.progress(manifest)

    def _validated_duration(self, path: Path) -> float | None:
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
                return None
            if not self.validator(path):
                return None
            duration = float(self.duration_reader(path))
            return duration if duration > 0 else None
        except Exception:
            return None

    def _promote_valid_partial(self, partial: Path, final: Path) -> float | None:
        duration = self._validated_duration(partial)
        if duration is None:
            self._remove_partial(partial)
            return None
        self._fsync_file(partial)
        os.replace(partial, final)
        self._fsync_directory(final.parent)
        return duration

    @staticmethod
    def _partial_path(final: Path) -> Path:
        return final.with_name(f"{final.stem}.partial.wav")

    @staticmethod
    def _remove_partial(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except IsADirectoryError:
            pass

    @staticmethod
    def _fsync_file(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _complete(
        self,
        manifest: JobManifest,
        position: int,
        path: Path,
        duration: float,
    ) -> JobManifest:
        chunk = replace(
            manifest.chunks[position],
            status=ChunkStatus.COMPLETE,
            audio_path=str(path),
            duration_seconds=duration,
            generated_at=manifest.chunks[position].generated_at or self.now(),
            last_error=None,
        )
        return self._replace_chunk(manifest, position, chunk)

    def _replace_chunk(
        self,
        manifest: JobManifest,
        position: int,
        chunk: Chunk,
    ) -> JobManifest:
        chunks = list(manifest.chunks)
        chunks[position] = chunk
        return replace(manifest, chunks=tuple(chunks), updated_at=self.now())

    def _fail_job(self, path: Path, manifest: JobManifest) -> None:
        self._save(path, replace(manifest, status=JobStatus.FAILED, updated_at=self.now()))
