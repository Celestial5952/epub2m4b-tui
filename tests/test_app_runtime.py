from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from epub2m4b.app.jobs import JobStore
from epub2m4b.app.library import LibraryBook, LibraryScan
from epub2m4b.config import AppConfig
from epub2m4b.config_store import ConfigRepository
from epub2m4b.generation.manifest import ManifestRepository
from epub2m4b.models import (
    Book,
    Chapter,
    Chunk,
    JobManifest,
    ManifestBook,
    ManifestSource,
    NarrationSettings,
)


@pytest.fixture(autouse=True)
def immediate_to_thread(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Exercise the offload boundary without sandbox-dependent worker threads."""

    calls: list[object] = []

    async def run(function: object, *args: object, **kwargs: object) -> object:
        calls.append(function)
        return function(*args, **kwargs)  # type: ignore[operator]

    monkeypatch.setattr(asyncio, "to_thread", run)
    return calls


def _manifest(job_id: str = "job-123") -> JobManifest:
    settings = NarrationSettings("openai", "model", "marin", 1.0, "read")
    return JobManifest(
        job_id=job_id,
        app_version="test",
        source=ManifestSource("book.epub", "a" * 64),
        book=ManifestBook("Book", ("Author",)),
        narration=settings,
        chunks=(),
    )


class OnboardingFake:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def state(self) -> object:
        self.calls.append(("state", None))
        return "state"

    def complete(
        self,
        voice_id: str,
        cache_directory: Path | None = None,
        book_directory: Path | None = None,
        **kwargs: object,
    ) -> None:
        self.calls.append(("complete", (voice_id, cache_directory, book_directory, kwargs)))

    def skip(self) -> None:
        self.calls.append(("skip", None))

    def set_credential(self, secret: str) -> None:
        self.calls.append(("set", secret))

    def remove_credential(self) -> None:
        self.calls.append(("remove", None))

    def set_elevenlabs_credential(self, secret: str) -> None:
        self.calls.append(("set_elevenlabs", secret))

    def remove_elevenlabs_credential(self) -> None:
        self.calls.append(("remove_elevenlabs", None))


class PlayerFake:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def play(self, path: Path) -> None:
        self.calls.append(("play", path))

    def stop(self) -> None:
        self.calls.append(("stop", None))

    def shutdown(self) -> None:
        self.calls.append(("shutdown", None))


class VoicesFake:
    def __init__(self, path: Path) -> None:
        self.entry = SimpleNamespace(id="marin", path=path)

    def get(self, voice_id: str) -> object:
        if voice_id != self.entry.id:
            raise KeyError(voice_id)
        return self.entry


def _service(tmp_path: Path, **overrides: object) -> object:
    from epub2m4b.app.runtime import LocalApplicationService

    default_preparer = lambda *args: SimpleNamespace(manifest=_manifest())  # noqa: E731
    return LocalApplicationService(
        config_path=tmp_path / "config.toml",
        onboarding=overrides.get("onboarding", OnboardingFake()),
        voices=overrides.get("voices", VoicesFake(tmp_path / "voice.opus")),
        player=overrides.get("player", PlayerFake()),
        jobs=overrides.get("jobs", JobStore(tmp_path / "jobs")),
        credentials=overrides.get("credentials"),
        audit=overrides.get("audit"),
        cache_root=overrides.get("cache_root", tmp_path / "cache"),
        output_directory=overrides.get("output_directory", tmp_path / "audiobooks"),
        inspector=overrides.get("inspector", lambda source: source),
        preparer=overrides.get("preparer", default_preparer),
        id_factory=overrides.get("id_factory", lambda: "123"),
        now=overrides.get("now", lambda: datetime(2026, 1, 2, tzinfo=UTC)),
        library_scanner=overrides.get("library_scanner", lambda root: LibraryScan(root, ())),
        provider_factory=overrides.get("provider_factory", lambda secret: object()),
        coordinator_factory=overrides.get(
            "coordinator_factory", lambda *args, **kwargs: object()
        ),
        assembler=overrides.get("assembler", lambda *args, **kwargs: object()),
        cover_reader=overrides.get("cover_reader", lambda source: None),
        duration_reader=overrides.get("duration_reader", lambda path: 1.0),
    )


def test_simple_methods_delegate_and_preview_validates_voice(tmp_path: Path) -> None:
    onboarding = OnboardingFake()
    player = PlayerFake()
    voices = VoicesFake(tmp_path / "preview.opus")
    service = _service(tmp_path, onboarding=onboarding, player=player, voices=voices)

    assert service.onboarding_state() == "state"
    service.complete_onboarding("marin")
    service.skip_onboarding()
    service.set_openai_credential("secret")
    service.remove_openai_credential()
    service.set_elevenlabs_credential("secret")
    service.remove_elevenlabs_credential()
    service.play_voice_preview("marin")
    service.stop_voice_preview()
    service.shutdown()

    complete_kwargs = {
        "output_directory": None,
        "provider": None,
        "model": None,
        "speed": None,
        "instructions": None,
        "maximum_estimated_cost_usd": None,
    }
    assert onboarding.calls == [
        ("state", None),
        ("complete", ("marin", None, None, complete_kwargs)),
        ("skip", None),
        ("set", "secret"),
        ("remove", None),
        ("set_elevenlabs", "secret"),
        ("remove_elevenlabs", None),
    ]
    assert player.calls == [
        ("play", tmp_path / "preview.opus"),
        ("stop", None),
        ("stop", None),
        ("shutdown", None),
    ]
    with pytest.raises(KeyError):
        service.play_voice_preview("unknown")


def test_inspect_book_offloads_injected_inspector(
    tmp_path: Path, immediate_to_thread: list[object]
) -> None:
    expected = object()

    def inspect(source: Path) -> object:
        assert source == tmp_path / "book.epub"
        return expected

    result = asyncio.run(_service(tmp_path, inspector=inspect).inspect_book(tmp_path / "book.epub"))
    assert result is expected
    assert immediate_to_thread == [inspect]


def test_create_job_builds_settings_offloads_and_round_trips_manifest(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    ConfigRepository.save(
        config_path,
        AppConfig(
            model="custom-model",
            voice="ash",
            speed=1.25,
            instructions="Narrate",
            generation_options={"x": "y"},
        ),
    )
    source = tmp_path / "book.epub"
    source.write_bytes(b"epub-bytes")
    seen: list[tuple[object, ...]] = []
    expected = _manifest("job-123")

    def prepare(*args: object) -> JobManifest:
        seen.append(args)
        return SimpleNamespace(manifest=expected)

    service = _service(tmp_path, preparer=prepare, id_factory=lambda: "123")
    result = asyncio.run(service.create_job(source))
    saved = ManifestRepository.load(tmp_path / "jobs" / "job-123" / "manifest.json")
    assert result == expected == saved
    assert len(seen) == 1
    prepared_source, settings, job_id, version, timestamp = seen[0]
    assert prepared_source == source
    assert settings == NarrationSettings(
        "openai", "custom-model", "ash", 1.25, "Narrate", {"x": "y"}
    )
    assert job_id == "job-123" and isinstance(version, str) and version
    assert timestamp == datetime(2026, 1, 2, tzinfo=UTC)


def test_create_job_migrates_retired_openai_model_even_without_onboarding_state(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_bytes(b"epub-bytes")
    ConfigRepository.save(tmp_path / "config.toml", AppConfig(model="gpt-4o-tts"))
    expected = _manifest("job-123")
    seen: list[NarrationSettings] = []

    def prepare(*args: object) -> JobManifest:
        seen.append(args[1])  # type: ignore[arg-type]
        return SimpleNamespace(manifest=expected)

    service = _service(tmp_path, preparer=prepare, id_factory=lambda: "123")

    asyncio.run(service.create_job(source))

    assert seen[0].model == "gpt-4o-mini-tts"
    assert ConfigRepository.load(tmp_path / "config.toml").model == "gpt-4o-mini-tts"


def test_unsafe_id_and_preparer_failure_do_not_write(tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    source.write_bytes(b"epub-bytes")
    service = _service(tmp_path, id_factory=lambda: "../escape")
    with pytest.raises(ValueError):
        asyncio.run(service.create_job(source))
    assert not (tmp_path / "jobs").exists()

    def fail(*args: object) -> JobManifest:
        raise RuntimeError("preparer failed")

    service = _service(tmp_path, preparer=fail, id_factory=lambda: "456")
    with pytest.raises(RuntimeError):
        asyncio.run(service.create_job(source))
    assert not (tmp_path / "job-456").exists()


def test_scan_book_folder_uses_configured_directory_off_thread(
    tmp_path: Path, immediate_to_thread: list[object]
) -> None:
    books = tmp_path / "books"
    ConfigRepository.save(
        tmp_path / "config.toml",
        AppConfig(book_directory=books),
    )
    expected = LibraryScan(
        books,
        (LibraryBook(books / "book.epub", Path("book.epub")),),
    )
    calls: list[Path] = []

    def scan(root: Path) -> LibraryScan:
        calls.append(root)
        return expected

    result = asyncio.run(_service(tmp_path, library_scanner=scan).scan_book_folder())

    assert result == expected
    assert calls == [books]
    assert immediate_to_thread == [scan]


def test_scan_book_folder_without_configuration_is_empty_and_local(
    tmp_path: Path, immediate_to_thread: list[object]
) -> None:
    result = asyncio.run(_service(tmp_path).scan_book_folder())
    assert result == LibraryScan(None, ())
    assert immediate_to_thread == []


def _chunked_manifest(tmp_path: Path, job_id: str = "job-123") -> JobManifest:
    settings = NarrationSettings("openai", "model", "marin", 1.0, "read")
    chunk = Chunk.create(
        chapter_index=0,
        chunk_index=0,
        text="Hello world, this is a narration chunk.",
        settings=settings,
    )
    return JobManifest(
        job_id=job_id,
        app_version="test",
        source=ManifestSource("book.epub", "a" * 64),
        book=ManifestBook("Book", ("Author",)),
        narration=settings,
        chunks=(chunk,),
    )


def _save_manifest(tmp_path: Path, manifest: JobManifest) -> None:
    store = JobStore(tmp_path / "jobs").ensure()
    ManifestRepository.save(store.manifest_path(manifest.job_id), manifest)


def _source_with_hash(tmp_path: Path, name: str = "book.epub") -> tuple[Path, str]:
    import hashlib

    source = tmp_path / name
    payload = b"epub-bytes-" + name.encode()
    source.write_bytes(payload)
    return source, hashlib.sha256(payload).hexdigest()


def _default_settings() -> NarrationSettings:
    config = AppConfig()
    return NarrationSettings(
        provider=config.provider,
        model=config.model,
        voice=config.voice,
        speed=config.speed,
        instructions=config.instructions,
        generation_options=dict(config.generation_options),
    )


def _manifest_for(
    source: Path,
    digest: str,
    job_id: str,
    settings: NarrationSettings,
) -> JobManifest:
    return JobManifest(
        job_id=job_id,
        app_version="test",
        source=ManifestSource(str(source), digest),
        book=ManifestBook("Book", ("Author",)),
        narration=settings,
        chunks=(),
    )


def test_duplicate_preparation_is_refused_and_existing_job_is_kept(tmp_path: Path) -> None:
    source, digest = _source_with_hash(tmp_path)
    existing = _manifest_for(source, digest, "job-existing", _default_settings())
    _save_manifest(tmp_path, existing)
    service = _service(tmp_path)

    from epub2m4b.exceptions import DuplicatePreparationError

    with pytest.raises(DuplicatePreparationError) as caught:
        asyncio.run(service.create_job(source))
    assert caught.value.existing_job_id == "job-existing"
    # The existing job is never discarded or rewritten.
    assert ManifestRepository.load(
        tmp_path / "jobs" / "job-existing" / "manifest.json"
    ) == existing
    assert [path.name for path in (tmp_path / "jobs").iterdir()] == ["job-existing"]


def test_duplicate_detection_matches_source_hash_and_settings(tmp_path: Path) -> None:
    source, digest = _source_with_hash(tmp_path)
    existing = _manifest_for(source, digest, "job-existing", _default_settings())
    _save_manifest(tmp_path, existing)

    # Same source bytes with the same narration settings are a duplicate.
    service = _service(tmp_path)
    from epub2m4b.exceptions import DuplicatePreparationError

    with pytest.raises(DuplicatePreparationError):
        asyncio.run(service.create_job(source))

    # The same book file with different narration settings may prepare anew.
    ConfigRepository.save(tmp_path / "config.toml", AppConfig(voice="nova"))
    service = _service(tmp_path)
    created = asyncio.run(service.create_job(source))
    assert created.job_id == "job-123"
    assert ManifestRepository.load(tmp_path / "jobs" / "job-123" / "manifest.json") == created


def test_duplicate_detection_skips_corrupt_manifests(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs").ensure()
    corrupt = store.root / "job-corrupt"
    corrupt.mkdir()
    (corrupt / "manifest.json").write_bytes(b"not json")
    service = _service(tmp_path)
    source = tmp_path / "book.epub"
    source.write_bytes(b"epub-bytes")
    created = asyncio.run(service.create_job(source))
    assert created.job_id == "job-123"
    assert (corrupt / "manifest.json").read_bytes() == b"not json"


def test_create_job_and_estimate_fail_closed_for_unverified_provider(
    tmp_path: Path,
) -> None:
    ConfigRepository.save(tmp_path / "config.toml", AppConfig(provider="elevenlabs"))
    source = tmp_path / "book.epub"
    source.write_bytes(b"epub-bytes")
    service = _service(tmp_path)

    from epub2m4b.exceptions import GenerationError

    with pytest.raises(GenerationError, match="UNTESTED"):
        asyncio.run(service.create_job(source))
    assert not (tmp_path / "jobs").exists()

    # Even a manifest prepared earlier must not produce an estimate.
    settings = NarrationSettings("elevenlabs", "model", "marin", 1.0, "read")
    manifest = JobManifest(
        job_id="job-123",
        app_version="test",
        source=ManifestSource(str(source), "b" * 64),
        book=ManifestBook("Book", ("Author",)),
        narration=settings,
        chunks=(),
    )
    _save_manifest(tmp_path, manifest)
    with pytest.raises(GenerationError, match="UNTESTED"):
        asyncio.run(service.estimate_job("job-123"))


def test_estimate_job_prices_remaining_openai_chunks(tmp_path: Path) -> None:
    manifest = _chunked_manifest(tmp_path)
    _save_manifest(tmp_path, manifest)
    service = _service(tmp_path)
    estimate = asyncio.run(service.estimate_job("job-123"))
    assert estimate.character_count == len(manifest.chunks[0].text)
    assert estimate.estimated_cost_usd > 0


def test_pause_and_cancel_require_active_generation(tmp_path: Path) -> None:
    from epub2m4b.exceptions import GenerationError

    service = _service(tmp_path)
    with pytest.raises(GenerationError, match="not active"):
        asyncio.run(service.pause("job-123"))
    with pytest.raises(GenerationError, match="not active"):
        asyncio.run(service.cancel("job-123"))


def test_startup_recovers_interrupted_running_job_as_resumable(tmp_path: Path) -> None:
    from dataclasses import replace

    from epub2m4b.models import ChunkStatus, JobStatus

    manifest = _chunked_manifest(tmp_path)
    interrupted = replace(
        manifest,
        status=JobStatus.RUNNING,
        chunks=(
            replace(
                manifest.chunks[0],
                status=ChunkStatus.GENERATING,
                attempt_count=1,
            ),
        ),
    )
    _save_manifest(tmp_path, interrupted)

    _service(tmp_path)

    recovered = ManifestRepository.load(
        tmp_path / "jobs" / "job-123" / "manifest.json"
    )
    assert recovered.status is JobStatus.PAUSED
    assert recovered.chunks[0].status is ChunkStatus.GENERATING
    assert recovered.chunks[0].attempt_count == 1


def test_open_audiobook_validates_and_uses_xdg_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    from epub2m4b.exceptions import GenerationError

    service = _service(tmp_path)
    with pytest.raises(GenerationError, match="not available"):
        service.open_audiobook(tmp_path / "missing.m4b")

    target = tmp_path / "Book.m4b"
    target.write_bytes(b"audio")
    launched: list[list[str]] = []

    class FakePopen:
        def __init__(self, args: list[str], **kwargs: object) -> None:
            launched.append(list(args))
            assert kwargs["stdout"] is subprocess.DEVNULL
            assert kwargs["stderr"] is subprocess.DEVNULL

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    service.open_audiobook(target)
    assert launched == [["xdg-open", str(target)]]

    def explode(*args: object, **kwargs: object) -> object:
        raise OSError("no desktop")

    monkeypatch.setattr(subprocess, "Popen", explode)
    with pytest.raises(GenerationError, match="could not open"):
        service.open_audiobook(target)


def test_generate_runs_fakes_and_reports_output_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    ConfigRepository.save(tmp_path / "config.toml", AppConfig(maximum_estimated_cost_usd=25.0))
    manifest = _chunked_manifest(tmp_path)
    _save_manifest(tmp_path, manifest)

    from dataclasses import replace

    from epub2m4b.models import ChunkStatus, JobStatus

    complete_manifest = replace(
        manifest,
        status=JobStatus.COMPLETE,
        chunks=(
            replace(manifest.chunks[0], status=ChunkStatus.COMPLETE, duration_seconds=1.5),
        ),
    )

    class FakeCoordinator:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.paused = False
            self.cancelled = False

        async def run(self, manifest_path: Path) -> object:
            loaded = ManifestRepository.load(manifest_path)
            assert loaded == manifest
            from epub2m4b.generation.coordinator import GenerationResult

            return GenerationResult(
                manifest=complete_manifest, synthesized_chunks=1, recovered_chunks=0
            )

        def request_pause(self) -> None:
            self.paused = True

        def request_cancel(self) -> None:
            self.cancelled = True

    class FakeProvider:
        def __init__(self, secret: str) -> None:
            self.secret = secret

    from epub2m4b.audio.m4b import AssemblyResult

    assembled: list[tuple[object, ...]] = []

    def assembler(
        run_manifest: JobManifest,
        titles: dict[int, str],
        destination: Path,
        *,
        bitrate_kbps: int,
        cover: object = None,
    ) -> AssemblyResult:
        assembled.append((run_manifest, dict(titles), destination, bitrate_kbps, cover))
        return AssemblyResult(path=destination, duration_seconds=1.5, size_bytes=4, chapters=())

    service = _service(
        tmp_path,
        provider_factory=lambda secret: FakeProvider(secret),
        coordinator_factory=lambda *args, **kwargs: FakeCoordinator(*args, **kwargs),
        assembler=assembler,
        inspector=lambda source: Book(
            source, "a" * 64, "Book", ("Author",), None, None, None, None, None,
            (Chapter(0, "Chapter 1", None, "", ""),),
        ),
        cover_reader=lambda source: None,
    )

    async def collect() -> list[object]:
        events = []
        async for event in service.generate("job-123", Decimal("1.00")):
            events.append(event)
        return events

    events = asyncio.run(collect())
    assert events
    final = events[-1]
    assert final.message.startswith("complete: ")
    assert final.output_path == str(tmp_path / "audiobooks" / "Book [job-123].m4b")
    assert final.completed_chunks == 1 and final.total_chunks == 1
    assert len(assembled) == 1
    run_manifest, titles, destination, bitrate, cover = assembled[0]
    assert run_manifest == complete_manifest
    assert destination == tmp_path / "audiobooks" / "Book [job-123].m4b"
    assert bitrate == 96 and cover is None


def test_generate_refuses_when_openai_unconfigured(tmp_path: Path) -> None:
    manifest = _chunked_manifest(tmp_path)
    _save_manifest(tmp_path, manifest)
    from epub2m4b.credentials import CredentialService
    from epub2m4b.exceptions import GenerationError

    class EmptyKeyring:
        def get_password(self, service: str, user: str) -> None:
            return None

    service = _service(tmp_path, credentials=CredentialService(EmptyKeyring()))

    async def run() -> None:
        async for _ in service.generate("job-123", Decimal("10.00")):
            pass

    with pytest.raises(GenerationError, match="OpenAI is not configured; add your API key in Settings"):
        asyncio.run(run())


def test_load_local_env_reads_file_without_overwriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from epub2m4b.app.runtime import _load_local_env

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    (tmp_path / ".env.local").write_text("OPENAI_API_KEY=sk-local-test-key\n", encoding="utf-8")
    _load_local_env()
    assert os.environ.get("OPENAI_API_KEY") == "sk-local-test-key"

    # Does not overwrite if already set in environment
    (tmp_path / ".env.local").write_text("OPENAI_API_KEY=sk-new-key\n", encoding="utf-8")
    _load_local_env()
    assert os.environ.get("OPENAI_API_KEY") == "sk-local-test-key"


def test_estimate_and_generate_job_preview(tmp_path: Path) -> None:
    manifest = _chunked_manifest(tmp_path)
    _save_manifest(tmp_path, manifest)

    from epub2m4b.providers.base import SynthesisRequest, SynthesisResult

    class FakeTTS:
        def __init__(self, secret: str) -> None:
            self.secret = secret

        async def synthesize(self, request: SynthesisRequest, destination: Path) -> SynthesisResult:
            destination.write_bytes(b"RIFF$fake-audio-bytes-wav")
            return SynthesisResult(request.request_id, 30.0, destination.stat().st_size)

    service = _service(
        tmp_path,
        provider_factory=lambda secret: FakeTTS(secret),
    )

    # Estimate preview
    estimate = asyncio.run(service.estimate_job_preview("job-123"))
    assert estimate.character_count > 0
    assert estimate.estimated_cost_usd > 0

    # No preview before generating
    assert service.get_job_preview("job-123") is None

    # Generate preview
    preview_path = asyncio.run(service.generate_job_preview("job-123", Decimal("1.00")))
    assert preview_path.is_file()
    assert preview_path.name.startswith("preview-job-123-")
    assert service.get_job_preview("job-123") == preview_path

    # Play preview audio
    service.play_audio_file(preview_path)
    assert any(call[0] == "play" and call[1] == preview_path for call in service.player.calls)

