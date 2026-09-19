"""Offline first-run onboarding orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Protocol

from ..config import migrate_retired_openai_model
from ..config_store import ConfigRepository
from ..credentials import CredentialService


class _VoiceRegistry(Protocol):
    @property
    def entries(self) -> tuple[Any, ...]: ...

    def get(self, voice_id: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class OnboardingState:
    """The complete non-secret snapshot needed by the first-run UI."""

    completed: bool
    selected_voice: str
    credential_status: str
    dependencies: object
    voices: tuple[Any, ...]
    cache_directory: Path | None = None
    book_directory: Path | None = None
    output_directory: Path | None = None
    provider: str = "openai"
    model: str = "gpt-4o-mini-tts"
    speed: float = 1.0
    instructions: str = ""
    maximum_estimated_cost_usd: float = 25.0


class OnboardingService:
    """Coordinate local onboarding state without making provider requests."""

    def __init__(
        self,
        config_path: Path,
        credentials: CredentialService,
        voices: _VoiceRegistry,
        dependency_checker: Callable[[], object],
        *,
        default_cache_directory: Path | None = None,
        default_book_directory: Path | None = None,
    ) -> None:
        self._config_path = Path(config_path)
        self._credentials = credentials
        self._voices = voices
        self._dependency_checker = dependency_checker
        self._default_cache_directory = default_cache_directory
        self._default_book_directory = default_book_directory

    def state(self, env: Mapping[str, str] | None = None) -> OnboardingState:
        config = ConfigRepository.load(self._config_path)
        migrated = migrate_retired_openai_model(config)
        if migrated != config:
            # This is an explicit, atomic compatibility migration for the one
            # retired model shipped in prior releases. It runs before any job
            # can be prepared, so old configuration cannot create a doomed job.
            ConfigRepository.save(self._config_path, migrated)
            config = migrated
        try:
            credential_status = self._credentials.status("openai", env)
        except Exception as exc:
            # Credential backend details are intentionally not part of UI state.
            # CredentialService raises CredentialError for unavailable backends;
            # catching defensively also protects the onboarding boundary from an
            # alternate backend leaking an implementation message.
            del exc
            credential_status = "unavailable"
        return OnboardingState(
            completed=config.onboarding_complete,
            selected_voice=config.voice,
            credential_status=credential_status,
            dependencies=self._dependency_checker(),
            voices=tuple(self._voices.entries),
            cache_directory=config.cache_directory or self._default_cache_directory,
            book_directory=config.book_directory or self._default_book_directory,
            output_directory=config.output_directory,
            provider=config.provider,
            model=config.model,
            speed=config.speed,
            instructions=config.instructions,
            maximum_estimated_cost_usd=config.maximum_estimated_cost_usd,
        )

    @staticmethod
    def _cache_path(value: str | Path | None) -> Path | None:
        if value is None:
            return None
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("cache directory must be an absolute path")
        try:
            path.mkdir(parents=True, exist_ok=True)
            resolved = path.resolve(strict=True)
        except OSError:
            raise ValueError("cache directory is unavailable") from None
        if not resolved.is_dir():
            raise ValueError("cache directory must be a directory")
        try:
            with NamedTemporaryFile(prefix=".epub2m4b-write-test-", dir=resolved):
                pass
        except OSError:
            raise ValueError("cache directory is not writable") from None
        return resolved

    @staticmethod
    def _book_path(value: str | Path | None) -> Path | None:
        if value is None:
            return None
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("book directory must be an absolute path")
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            raise ValueError("book directory is unavailable") from None
        if not resolved.is_dir():
            raise ValueError("book directory must be a directory")
        return resolved

    @staticmethod
    def _output_path(value: str | Path | None) -> Path | None:
        if value is None:
            return None
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("output directory must be an absolute path")
        try:
            path.mkdir(parents=True, exist_ok=True)
            resolved = path.resolve(strict=True)
        except OSError:
            raise ValueError("output directory is unavailable") from None
        if not resolved.is_dir():
            raise ValueError("output directory must be a directory")
        try:
            with NamedTemporaryFile(prefix=".epub2m4b-write-test-", dir=resolved):
                pass
        except OSError:
            raise ValueError("output directory is not writable") from None
        return resolved

    def complete(
        self,
        voice_id: str,
        cache_directory: str | Path | None = None,
        book_directory: str | Path | None = None,
        *,
        output_directory: str | Path | None = None,
        provider: str | None = None,
        model: str | None = None,
        speed: float | None = None,
        instructions: str | None = None,
        maximum_estimated_cost_usd: float | None = None,
    ) -> None:
        """Select a voice, storage locations, and narration defaults, then save."""

        # Validate before loading/saving so an invalid selection cannot write.
        self._voices.get(voice_id)
        config = ConfigRepository.load(self._config_path)
        books = self._book_path(book_directory)
        cache = self._cache_path(cache_directory)
        output = self._output_path(output_directory)
        ConfigRepository.save(
            self._config_path,
            replace(
                config,
                onboarding_complete=True,
                voice=voice_id,
                cache_directory=cache if cache_directory is not None else config.cache_directory,
                book_directory=books if book_directory is not None else config.book_directory,
                output_directory=(
                    output if output_directory is not None else config.output_directory
                ),
                provider=provider if provider is not None else config.provider,
                model=model if model is not None else config.model,
                speed=speed if speed is not None else config.speed,
                instructions=instructions if instructions is not None else config.instructions,
                maximum_estimated_cost_usd=(
                    maximum_estimated_cost_usd
                    if maximum_estimated_cost_usd is not None
                    else config.maximum_estimated_cost_usd
                ),
            ),
        )

    def skip(self) -> None:
        """Mark onboarding complete while preserving the current configuration."""

        config = ConfigRepository.load(self._config_path)
        ConfigRepository.save(self._config_path, replace(config, onboarding_complete=True))

    def set_credential(self, secret: str) -> None:
        self._credentials.set("openai", secret)

    def remove_credential(self) -> None:
        self._credentials.delete("openai")


__all__ = ["OnboardingService", "OnboardingState"]
