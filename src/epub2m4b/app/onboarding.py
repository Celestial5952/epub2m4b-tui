"""Offline first-run onboarding orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Protocol

from ..config import migrate_retired_openai_model
from ..config_store import ConfigRepository
from ..credentials import CredentialService
from ..providers.registry import (
    TEXT_TO_SPEECH,
    ProviderRegistry,
    ProviderRegistryError,
    default_provider_registry,
)


class _VoiceRegistry(Protocol):
    @property
    def entries(self) -> tuple[Any, ...]: ...

    def get(self, voice_id: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class ProviderOption:
    """A narration provider the listener can pick, plus their key status.

    Built from the provider registry so the UI never hard-codes a provider.
    """

    id: str
    name: str
    label: str
    live_verified: bool
    default_model: str
    key_url: str
    billing_url: str
    credential_env: str
    credential_status: str = "unconfigured"


def provider_options(
    statuses: Mapping[str, str] | None = None,
    registry: ProviderRegistry | None = None,
) -> tuple[ProviderOption, ...]:
    """List every text-to-speech provider in registry order."""

    known = statuses or {}
    return tuple(
        ProviderOption(
            id=entry.id,
            name=entry.name,
            label=entry.choice_label,
            live_verified=entry.live_verified,
            default_model=entry.default_model,
            key_url=entry.key_url,
            billing_url=entry.billing_url,
            credential_env=entry.credential_env,
            credential_status=known.get(entry.id, "unconfigured"),
        )
        for entry in (registry or default_provider_registry()).for_capability(TEXT_TO_SPEECH)
    )


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
    elevenlabs_credential_status: str = "unconfigured"
    providers: tuple[ProviderOption, ...] = field(default_factory=provider_options)


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
        registry: ProviderRegistry | None = None,
    ) -> None:
        self._registry = registry or default_provider_registry()
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
        options = provider_options(registry=self._registry)
        statuses: dict[str, str] = {}
        for option in options:
            try:
                statuses[option.id] = self._credentials.status(option.id, env)
            except Exception as exc:
                del exc
                statuses[option.id] = "unavailable"
        credential_status = statuses.get("openai", "unconfigured")
        elevenlabs_status = statuses.get("elevenlabs", "unconfigured")
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
            elevenlabs_credential_status=elevenlabs_status,
            providers=provider_options(statuses, self._registry),
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
        if provider is not None:
            self._require_narration_provider(provider)
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

    def _require_narration_provider(self, provider_id: str) -> None:
        """Only a registered, live-verified provider may become the narration provider."""

        try:
            entry = self._registry.get(provider_id)
        except ProviderRegistryError:
            raise ValueError("unknown narration provider") from None
        if not entry.live_verified:
            raise ValueError(f"{entry.name} narration is UNTESTED live and cannot be selected yet")

    def skip(self) -> None:
        """Mark onboarding complete while preserving the current configuration."""

        config = ConfigRepository.load(self._config_path)
        ConfigRepository.save(self._config_path, replace(config, onboarding_complete=True))

    def set_provider_credential(self, provider_id: str, secret: str) -> None:
        self._credentials.set(provider_id, secret)

    def remove_provider_credential(self, provider_id: str) -> None:
        self._credentials.delete(provider_id)

    def set_credential(self, secret: str) -> None:
        self.set_provider_credential("openai", secret)

    def remove_credential(self) -> None:
        self.remove_provider_credential("openai")

    def set_elevenlabs_credential(self, secret: str) -> None:
        self.set_provider_credential("elevenlabs", secret)

    def remove_elevenlabs_credential(self) -> None:
        self.remove_provider_credential("elevenlabs")


__all__ = ["OnboardingService", "OnboardingState", "ProviderOption", "provider_options"]
