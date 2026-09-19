"""Composition root for the local, provider-free application workflow."""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from epub2m4b import __version__
from epub2m4b.app.audit import (
    ASSEMBLY,
    AUTHORIZED,
    CACHED,
    CANCELLED,
    COMPLETE,
    CONNECTION,
    CREDENTIAL,
    ESTIMATE,
    FAILURE,
    JOB,
    PAUSED,
    SUCCESS,
    AuditedTTSProvider,
    AuditEntry,
    AuditLog,
    sanitize,
)
from epub2m4b.app.events import ProgressEvent
from epub2m4b.app.jobs import JobStore, JobSummary
from epub2m4b.app.library import LibraryScan, scan_epub_folder
from epub2m4b.app.onboarding import OnboardingService, OnboardingState
from epub2m4b.app.reset import force_reonboard
from epub2m4b.audio.m4b import AssemblyResult, assemble_m4b
from epub2m4b.audio.player import AudioPlayer
from epub2m4b.audio.tools import probe_duration
from epub2m4b.config import migrate_retired_openai_model
from epub2m4b.config_store import ConfigRepository
from epub2m4b.credentials import CredentialService
from epub2m4b.dependencies import check_dependencies
from epub2m4b.epub.cover import CoverImage, read_cover
from epub2m4b.epub.parser import inspect_book
from epub2m4b.exceptions import DuplicatePreparationError, EpubError, GenerationError
from epub2m4b.generation.cache import AudioCache
from epub2m4b.generation.chunker import chunk_text
from epub2m4b.generation.coordinator import GenerationCoordinator
from epub2m4b.generation.estimate import (
    NarrationEstimate,
    TTSPricing,
    estimate_narration,
)
from epub2m4b.generation.job import PreparedJob, prepare_job
from epub2m4b.generation.manifest import ManifestRepository
from epub2m4b.models import (
    Book,
    Chunk,
    ChunkStatus,
    JobManifest,
    JobStatus,
    NarrationSettings,
)
from epub2m4b.paths import AppPaths
from epub2m4b.providers.base import SynthesisRequest, TTSProvider
from epub2m4b.providers.openai_tts import OpenAITTSProvider
from epub2m4b.voice_registry import VoiceRegistry

_OPENAI_TTS_PRICING = TTSPricing("0.60", "12.00", "20")


def _load_local_env() -> None:
    """Load development environment variables from .env.local or .env if present."""
    if "OPENAI_API_KEY" in os.environ:
        return
    for filename in (".env.local", ".env"):
        env_file = Path(filename)
        if not env_file.is_file():
            continue
        try:
            for raw_line in env_file.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line.removeprefix("export ").lstrip()
                name, separator, value = line.partition("=")
                if separator and name.strip() == "OPENAI_API_KEY":
                    val = value.strip().strip("'\"")
                    if val:
                        os.environ["OPENAI_API_KEY"] = val
                        return
        except OSError:
            pass


class LocalApplicationService:
    """Wire local UI capabilities without creating a narration provider."""

    def __init__(
        self,
        config_path: Path,
        onboarding: OnboardingService,
        voices: VoiceRegistry,
        player: AudioPlayer,
        jobs: JobStore,
        *,
        credentials: CredentialService | None = None,
        cache_root: Path | None = None,
        output_directory: Path | None = None,
        audit: AuditLog | None = None,
        inspector: Callable[[Path], Book] = inspect_book,
        preparer: Callable[..., PreparedJob] = prepare_job,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        provider_factory: Callable[[str], TTSProvider] = OpenAITTSProvider,
        coordinator_factory: Callable[..., GenerationCoordinator] = GenerationCoordinator,
        assembler: Callable[..., AssemblyResult] = assemble_m4b,
        cover_reader: Callable[[Path], CoverImage | None] = read_cover,
        duration_reader: Callable[[Path], float] = probe_duration,
        library_scanner: Callable[[Path], LibraryScan] = scan_epub_folder,
    ) -> None:
        self.config_path = Path(config_path)
        self.onboarding = onboarding
        self.voices = voices
        self.player = player
        self.jobs = jobs
        self.credentials = credentials or CredentialService()
        self.cache_root = Path(cache_root or jobs.root.parent / "cache")
        self.output_directory = Path(output_directory or jobs.root.parent / "audiobooks")
        self.audit = audit or AuditLog(jobs.root.parent / "logs" / "audit.jsonl")
        self._inspector = inspector
        self._preparer = preparer
        self._id_factory = id_factory
        self._now = now
        self._provider_factory = provider_factory
        self._coordinator_factory = coordinator_factory
        self._assembler = assembler
        self._cover_reader = cover_reader
        self._duration_reader = duration_reader
        self._library_scanner = library_scanner
        self._active: dict[str, GenerationCoordinator] = {}
        self._recover_interrupted_jobs()

    def _recover_interrupted_jobs(self) -> None:
        """Make jobs left running by an earlier process explicitly resumable."""

        for manifest in self.jobs.manifests():
            if manifest.status is not JobStatus.RUNNING:
                continue
            recovered = replace(
                manifest,
                status=JobStatus.PAUSED,
                updated_at=self._now().isoformat(),
            )
            ManifestRepository.save(self.jobs.manifest_path(manifest.job_id), recovered)
            self._audit_record(
                PAUSED,
                "interrupted narration recovered and made ready to resume",
                provider=manifest.narration.provider,
                job_id=manifest.job_id,
                model=manifest.narration.model,
                voice=manifest.narration.voice,
            )

    @classmethod
    def create_default(cls, paths: AppPaths | None = None) -> LocalApplicationService:
        _load_local_env()
        resolved = (paths or AppPaths.resolve()).ensure()
        config_path = resolved.config / "config.toml"
        voices = VoiceRegistry.load_bundled()
        credentials = CredentialService()
        onboarding = OnboardingService(
            config_path,
            credentials,
            voices,
            check_dependencies,
            default_cache_directory=resolved.cache / "audio",
            default_book_directory=Path.home() / "Books",
        )
        return cls(
            config_path,
            onboarding,
            voices,
            AudioPlayer(),
            JobStore(resolved.state / "jobs").ensure(),
            credentials=credentials,
            cache_root=resolved.cache / "audio",
            output_directory=Path.home() / "Audiobooks",
            audit=AuditLog(resolved.state / "logs" / "audit.jsonl"),
        )

    def _audit_record(
        self,
        kind: str,
        message: str,
        *,
        provider: str | None = None,
        job_id: str | None = None,
        request_id: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        characters: int | None = None,
    ) -> None:
        """Best-effort audit write; logging must never break paid narration."""

        with suppress(Exception):
            self.audit.record(
                kind,
                message,
                provider=provider,
                job_id=job_id,
                request_id=request_id,
                model=model,
                voice=voice,
                characters=characters,
            )

    def onboarding_state(self) -> OnboardingState:
        return self.onboarding.state()

    def complete_onboarding(
        self,
        voice_id: str,
        cache_directory: Path | None = None,
        book_directory: Path | None = None,
        *,
        output_directory: Path | None = None,
        provider: str | None = None,
        model: str | None = None,
        speed: float | None = None,
        instructions: str | None = None,
        maximum_estimated_cost_usd: float | None = None,
    ) -> None:
        self.onboarding.complete(
            voice_id,
            cache_directory,
            book_directory,
            output_directory=output_directory,
            provider=provider,
            model=model,
            speed=speed,
            instructions=instructions,
            maximum_estimated_cost_usd=maximum_estimated_cost_usd,
        )

    def skip_onboarding(self) -> None:
        self.onboarding.skip()

    def set_openai_credential(self, secret: str) -> None:
        self.onboarding.set_credential(secret)
        self._audit_record(
            CREDENTIAL, "OpenAI API key saved to the system keyring", provider="openai"
        )

    def remove_openai_credential(self) -> None:
        self.onboarding.remove_credential()
        self._audit_record(CREDENTIAL, "saved OpenAI API key removed", provider="openai")

    def set_elevenlabs_credential(self, secret: str) -> None:
        self.onboarding.set_elevenlabs_credential(secret)
        self._audit_record(
            CREDENTIAL, "ElevenLabs API key saved to the system keyring", provider="elevenlabs"
        )

    def remove_elevenlabs_credential(self) -> None:
        self.onboarding.remove_elevenlabs_credential()
        self._audit_record(CREDENTIAL, "saved ElevenLabs API key removed", provider="elevenlabs")

    def force_reonboard(self) -> Path:
        """Export non-secret history and return this installation to first run."""

        if self._active:
            raise GenerationError("wait for active narration to stop before resetting")
        export_name = f"epub2m4b-reset-{self._now().strftime('%Y%m%dT%H%M%SZ')}.json"
        export_path = Path.home() / export_name
        self.player.stop()
        return force_reonboard(
            config_path=self.config_path,
            audit=self.audit,
            jobs_root=self.jobs.root,
            cache_root=self.cache_root,
            credentials=self.credentials,
            export_path=export_path,
            exported_at=self._now(),
        )

    async def test_openai_connection(self, model: str) -> str:
        """Check the saved key and model permission without generating audio."""

        credential = self.credentials.get("openai")
        if credential is None:
            raise GenerationError("save an OpenAI API key before testing")
        provider = self._provider_factory(credential.secret)
        checker = getattr(provider, "check_model_access", None)
        if not callable(checker):
            raise GenerationError("OpenAI connection test is unavailable")
        try:
            verified_model = await checker(model)
        except Exception as exc:
            self._audit_record(
                FAILURE,
                f"OpenAI connection test failed: {sanitize(str(exc))}",
                provider="openai",
                model=model,
            )
            raise
        self._audit_record(
            CONNECTION,
            "OpenAI connection, API key, and model access verified",
            provider="openai",
            model=verified_model,
        )
        return verified_model

    def play_voice_preview(self, voice_id: str) -> None:
        entry = self.voices.get(voice_id)
        self.player.play(entry.path)

    def play_audio_file(self, path: Path) -> None:
        self.player.play(path)

    def stop_voice_preview(self) -> None:
        self.player.stop()

    def shutdown(self) -> None:
        for coordinator in tuple(self._active.values()):
            coordinator.request_pause()
        self.player.stop()
        self.player.shutdown()

    async def inspect_book(self, source: Path) -> Book:
        return await asyncio.to_thread(self._inspector, Path(source))

    async def scan_book_folder(self) -> LibraryScan:
        config = ConfigRepository.load(self.config_path)
        if config.book_directory is None:
            return LibraryScan(None, ())
        return await asyncio.to_thread(self._library_scanner, config.book_directory)

    @staticmethod
    def _hash_source(source: Path) -> str:
        digest = hashlib.sha256()
        try:
            with Path(source).open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
        except OSError as exc:
            raise EpubError(f"could not read EPUB source: {source}") from exc
        return digest.hexdigest()

    def _find_duplicate(self, source_sha256: str, settings: NarrationSettings) -> str | None:
        """Return the ID of an existing equivalent job, if one exists."""

        for manifest in self.jobs.manifests():
            if manifest.source.sha256 == source_sha256 and manifest.narration == settings:
                return manifest.job_id
        return None

    async def create_job(self, source: Path) -> JobManifest:
        config = ConfigRepository.load(self.config_path)
        migrated = migrate_retired_openai_model(config)
        if migrated != config:
            ConfigRepository.save(self.config_path, migrated)
            config = migrated
        self._require_supported_provider(config.provider)
        settings = NarrationSettings(
            provider=config.provider,
            model=config.model,
            voice=config.voice,
            speed=config.speed,
            instructions=config.instructions,
            generation_options=dict(config.generation_options),
        )
        source = Path(source)
        source_sha256 = await asyncio.to_thread(self._hash_source, source)
        duplicate = await asyncio.to_thread(self._find_duplicate, source_sha256, settings)
        if duplicate is not None:
            raise DuplicatePreparationError(duplicate)
        job_id = f"job-{self._id_factory()}"
        manifest_path = self.jobs.manifest_path(job_id)
        prepared = await asyncio.to_thread(
            self._preparer,
            source,
            settings,
            job_id,
            __version__,
            self._now(),
        )
        if prepared.manifest.job_id != job_id:
            raise ValueError("prepared manifest job ID does not match the requested job")
        ManifestRepository.save(manifest_path, prepared.manifest)
        self._audit_record(
            JOB,
            f"prepared audiobook job '{prepared.manifest.book.title}' "
            f"with {len(prepared.manifest.chunks)} audio piece(s)",
            provider=settings.provider,
            job_id=job_id,
            model=settings.model,
            voice=settings.voice,
            characters=sum(len(chunk.text) for chunk in prepared.manifest.chunks),
        )
        return prepared.manifest

    async def list_jobs(self) -> tuple[JobSummary, ...]:
        return await asyncio.to_thread(self.jobs.list)

    async def delete_job(self, job_id: str) -> None:
        """Delete one inactive job record while preserving narration cache."""

        if job_id in self._active:
            raise GenerationError("stop the active narration before deleting this job")
        await asyncio.to_thread(self.jobs.delete, job_id)
        self._audit_record(JOB, "old audiobook job deleted", job_id=job_id)

    @staticmethod
    def _require_supported_provider(provider: str) -> None:
        """Refuse paid work for providers that have not passed live verification."""

        if provider != "openai":
            raise GenerationError(
                "ElevenLabs narration is marked UNTESTED live and is not "
                "available in this version; choose OpenAI in Settings"
            )

    async def estimate_job(self, job_id: str) -> NarrationEstimate:
        manifest_path = self.jobs.manifest_path(job_id)

        def estimate() -> NarrationEstimate:
            manifest = ManifestRepository.load(manifest_path)
            self._require_supported_provider(manifest.narration.provider)
            remaining = (
                chunk for chunk in manifest.chunks if chunk.status is not ChunkStatus.COMPLETE
            )
            return estimate_narration(
                remaining,
                _OPENAI_TTS_PRICING,
                words_per_minute="120",
                safety_multiplier="1.15",
            )

        return await asyncio.to_thread(estimate)

    def _preview_chunk_for_job(self, manifest: JobManifest) -> Chunk:
        first = next((c for c in manifest.chunks if c.text.strip()), None)
        if first is None:
            raise GenerationError("no text is available for preview in this book")
        preview_chunks = chunk_text(
            first.text,
            chapter_index=0,
            settings=manifest.narration,
            target_chars=500,
            max_chars=700,
        )
        if not preview_chunks:
            raise GenerationError("could not generate preview text for this book")
        return preview_chunks[0]

    async def estimate_job_preview(self, job_id: str) -> NarrationEstimate:
        manifest_path = self.jobs.manifest_path(job_id)

        def estimate() -> NarrationEstimate:
            manifest = ManifestRepository.load(manifest_path)
            self._require_supported_provider(manifest.narration.provider)
            chunk = self._preview_chunk_for_job(manifest)
            return estimate_narration(
                (chunk,),
                _OPENAI_TTS_PRICING,
                words_per_minute="120",
                safety_multiplier="1.15",
            )

        return await asyncio.to_thread(estimate)

    async def generate_job_preview(
        self,
        job_id: str,
        authorized_max_cost_usd: Decimal,
    ) -> Path:
        authorization = self._authorized_cost(authorized_max_cost_usd)
        estimate = await self.estimate_job_preview(job_id)
        config = ConfigRepository.load(self.config_path)
        configured_cap = Decimal(str(config.maximum_estimated_cost_usd))
        if estimate.estimated_cost_usd > authorization:
            raise GenerationError("preview estimate exceeds the authorized cost cap")
        if estimate.estimated_cost_usd > configured_cap:
            raise GenerationError("preview estimate exceeds the configured spending cap")

        manifest_path = self.jobs.manifest_path(job_id)
        manifest = await asyncio.to_thread(ManifestRepository.load, manifest_path)
        preview_chunk = self._preview_chunk_for_job(manifest)

        previews_dir = self.cache_root / "previews"
        await asyncio.to_thread(previews_dir.mkdir, parents=True, exist_ok=True)
        destination = previews_dir / f"preview-{job_id}-{preview_chunk.generation_hash[:12]}.wav"

        if (
            destination.is_file()
            and not destination.is_symlink()
            and destination.stat().st_size > 0
        ):
            return destination

        credential = self.credentials.get("openai")
        if credential is None:
            raise GenerationError(
                "OpenAI is not configured; add your API key in Settings or set OPENAI_API_KEY"
            )

        provider = AuditedTTSProvider(
            self._provider_factory(credential.secret),
            self.audit,
            job_id=job_id,
        )

        temp_destination = destination.with_suffix(
            f".tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}.wav"
        )
        request = SynthesisRequest(
            text=preview_chunk.text,
            model=manifest.narration.model,
            voice=manifest.narration.voice,
            speed=manifest.narration.speed,
            instructions=manifest.narration.instructions,
            request_id=f"preview-{self._id_factory()}",
        )

        try:
            await provider.synthesize(request, temp_destination)
            if not temp_destination.is_file() or temp_destination.stat().st_size <= 0:
                raise GenerationError("preview audio synthesis produced an empty file")
            temp_destination.replace(destination)
        except Exception:
            with suppress(OSError):
                temp_destination.unlink(missing_ok=True)
            raise

        self._audit_record(
            SUCCESS,
            f"generated book preview sample for '{manifest.book.title}'",
            provider="openai",
            job_id=job_id,
            model=manifest.narration.model,
            voice=manifest.narration.voice,
            characters=len(preview_chunk.text),
        )
        return destination

    def get_job_preview(self, job_id: str) -> Path | None:
        previews_dir = self.cache_root / "previews"
        if not previews_dir.is_dir():
            return None
        try:
            for item in previews_dir.iterdir():
                if (
                    item.is_file()
                    and not item.is_symlink()
                    and item.name.startswith(f"preview-{job_id}-")
                    and item.name.endswith(".wav")
                    and item.stat().st_size > 0
                ):
                    return item
        except OSError:
            return None
        return None

    @staticmethod
    def _authorized_cost(value: Decimal) -> Decimal:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise GenerationError("authorized cost must be a finite positive amount") from exc
        if not result.is_finite() or result <= 0:
            raise GenerationError("authorized cost must be a finite positive amount")
        return result

    @staticmethod
    def _progress_event(
        manifest: JobManifest,
        message: str | None = None,
        *,
        output_path: str | None = None,
    ) -> ProgressEvent:
        current = next(
            (
                chunk
                for chunk in manifest.chunks
                if chunk.status in {ChunkStatus.GENERATING, ChunkStatus.FAILED}
            ),
            None,
        )
        completed = sum(1 for chunk in manifest.chunks if chunk.status is ChunkStatus.COMPLETE)
        return ProgressEvent(
            job_id=manifest.job_id,
            chapter_index=current.chapter_index if current else None,
            chunk_index=current.chunk_index if current else None,
            completed_chunks=completed,
            total_chunks=len(manifest.chunks),
            message=message or manifest.status.value,
            output_path=output_path,
        )

    @staticmethod
    def _filename(title: str, job_id: str) -> str:
        stem = "".join(
            character if character.isalnum() or character in " -_." else "_" for character in title
        ).strip(" ._")
        return f"{stem or 'Audiobook'} [{job_id}].m4b"

    async def _assemble(self, manifest: JobManifest) -> AssemblyResult:
        source = Path(manifest.source.path)
        book = await asyncio.to_thread(self._inspector, source)
        cover = await asyncio.to_thread(self._cover_reader, source)
        config = ConfigRepository.load(self.config_path)
        destination_root = config.output_directory or self.output_directory
        destination = destination_root / self._filename(manifest.book.title, manifest.job_id)
        titles = {chapter.index: chapter.title for chapter in book.chapters}
        return await asyncio.to_thread(
            self._assembler,
            manifest,
            titles,
            destination,
            bitrate_kbps=config.aac_bitrate_kbps,
            cover=cover,
        )

    async def generate(
        self,
        job_id: str,
        authorized_max_cost_usd: Decimal,
    ) -> AsyncIterator[ProgressEvent]:
        if job_id in self._active:
            raise GenerationError("job generation is already active")
        authorization = self._authorized_cost(authorized_max_cost_usd)
        estimate = await self.estimate_job(job_id)
        self._audit_record(
            ESTIMATE,
            f"estimate for remaining narration: ${estimate.estimated_cost_usd} "
            f"for {estimate.character_count} characters "
            f"(about {estimate.estimated_seconds} seconds of audio)",
            provider="openai",
            job_id=job_id,
            characters=estimate.character_count,
        )
        config = ConfigRepository.load(self.config_path)
        configured_cap = Decimal(str(config.maximum_estimated_cost_usd))
        if estimate.estimated_cost_usd > authorization:
            self._audit_record(
                FAILURE,
                f"refused to start: estimate ${estimate.estimated_cost_usd} exceeds "
                f"the typed confirmation ceiling ${authorization}",
                provider="openai",
                job_id=job_id,
            )
            raise GenerationError("estimate exceeds the authorized cost cap")
        if estimate.estimated_cost_usd > configured_cap:
            self._audit_record(
                FAILURE,
                f"refused to start: estimate ${estimate.estimated_cost_usd} exceeds "
                f"the Settings spending cap ${configured_cap}",
                provider="openai",
                job_id=job_id,
            )
            raise GenerationError("estimate exceeds the configured cost cap")
        self._audit_record(
            AUTHORIZED,
            f"typed confirmation accepted: narration authorized up to ${authorization}",
            provider="openai",
            job_id=job_id,
        )

        credential = self.credentials.get("openai")
        if credential is None:
            self._audit_record(
                FAILURE,
                "refused to start: no OpenAI API key is configured",
                provider="openai",
                job_id=job_id,
            )
            raise GenerationError(
                "OpenAI is not configured; add your API key in Settings or set OPENAI_API_KEY"
            )
        provider = AuditedTTSProvider(
            self._provider_factory(credential.secret),
            self.audit,
            job_id=job_id,
        )
        manifest_path = self.jobs.manifest_path(job_id)
        cached_pieces = sum(
            1
            for chunk in ManifestRepository.load(manifest_path).chunks
            if chunk.status is ChunkStatus.COMPLETE
        )
        if cached_pieces:
            self._audit_record(
                CACHED,
                f"{cached_pieces} audio piece(s) already saved from earlier runs — "
                "no provider charge for them",
                provider="openai",
                job_id=job_id,
            )
        queue: asyncio.Queue[ProgressEvent | object] = asyncio.Queue()
        finished = object()

        def observe(manifest: JobManifest) -> None:
            queue.put_nowait(self._progress_event(manifest))

        coordinator = self._coordinator_factory(
            provider,
            AudioCache(config.cache_directory or self.cache_root),
            validator=lambda path: self._duration_reader(path) > 0,
            duration_reader=self._duration_reader,
            progress=observe,
        )
        self._active[job_id] = coordinator
        task = asyncio.create_task(coordinator.run(manifest_path))
        task.add_done_callback(lambda _: queue.put_nowait(finished))
        try:
            while True:
                item = await queue.get()
                if item is finished:
                    break
                yield item  # type: ignore[misc]
            result = await task
            status = result.manifest.status
            total = len(result.manifest.chunks)
            if status is JobStatus.COMPLETE:
                self._audit_record(
                    COMPLETE,
                    f"narration complete: {result.synthesized_chunks} piece(s) newly "
                    f"synthesized this run, {result.recovered_chunks} reused from "
                    f"cache, {total} total",
                    provider="openai",
                    job_id=job_id,
                )
                assembly = await self._assemble(result.manifest)
                self._audit_record(
                    ASSEMBLY,
                    f"audiobook written to {assembly.path}",
                    provider="openai",
                    job_id=job_id,
                )
                yield self._progress_event(
                    result.manifest,
                    f"complete: {assembly.path}",
                    output_path=str(assembly.path),
                )
            elif status is JobStatus.PAUSED:
                self._audit_record(
                    PAUSED,
                    f"narration paused with {total} audio piece(s) total",
                    provider="openai",
                    job_id=job_id,
                )
            elif status is JobStatus.CANCELLED:
                self._audit_record(
                    CANCELLED,
                    f"narration cancelled with {total} audio piece(s) total",
                    provider="openai",
                    job_id=job_id,
                )
        except Exception as exc:
            self._audit_record(
                FAILURE,
                f"generation stopped: {type(exc).__name__}: {sanitize(str(exc))}",
                provider="openai",
                job_id=job_id,
            )
            raise
        finally:
            self._active.pop(job_id, None)

    async def pause(self, job_id: str) -> None:
        try:
            coordinator = self._active[job_id]
        except KeyError as exc:
            raise GenerationError("job generation is not active") from exc
        coordinator.request_pause()

    async def resume(
        self,
        job_id: str,
        authorized_max_cost_usd: Decimal,
    ) -> AsyncIterator[ProgressEvent]:
        async for event in self.generate(job_id, authorized_max_cost_usd):
            yield event

    async def cancel(self, job_id: str) -> None:
        try:
            coordinator = self._active[job_id]
        except KeyError as exc:
            raise GenerationError("job generation is not active") from exc
        coordinator.request_cancel()

    def open_audiobook(self, path: Path) -> None:
        """Open a finished audiobook with the desktop's default player."""

        target = Path(path)
        if not target.is_file() or target.is_symlink():
            raise GenerationError("audiobook file is not available")
        try:
            subprocess.Popen(  # noqa: S603
                ["xdg-open", str(target)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise GenerationError("could not open the audiobook on this computer") from exc

    async def audit_entries(self, limit: int = 200) -> tuple[AuditEntry, ...]:
        """Read audit entries newest-first for the Logs screen."""

        return await asyncio.to_thread(self.audit.entries, limit)

    def audit_log_location(self) -> Path:
        """Where the audit trail is stored, for display in the Logs screen."""

        return self.audit.path


__all__ = ["LocalApplicationService"]
