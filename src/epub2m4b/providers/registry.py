"""Provider metadata and capability selection."""

import re
from dataclasses import dataclass

TEXT_TO_SPEECH = "text_to_speech"
_SAFE_ID = re.compile(r"^[a-z][a-z0-9_-]*$")
_SAFE_ENV = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ProviderRegistryError(ValueError):
    """Raised when provider metadata or capability selection is invalid."""


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    id: str
    display_name: str
    credential_env: str
    capabilities: frozenset[str]

    def __post_init__(self) -> None:
        values = (self.id, self.display_name, self.credential_env)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ProviderRegistryError("provider metadata fields must be non-blank strings")
        if not _SAFE_ID.fullmatch(self.id):
            raise ProviderRegistryError(f"unsafe provider id: {self.id!r}")
        if not _SAFE_ENV.fullmatch(self.credential_env):
            raise ProviderRegistryError(
                f"invalid credential environment name: {self.credential_env!r}"
            )
        if not isinstance(self.capabilities, frozenset) or any(
            not isinstance(capability, str) or not capability.strip()
            for capability in self.capabilities
        ):
            raise ProviderRegistryError("capabilities must be a non-empty-string frozenset")


@dataclass(frozen=True, slots=True)
class ProviderRegistry:
    _entries: tuple[ProviderMetadata, ...]

    def __post_init__(self) -> None:
        entries = tuple(self._entries)
        if any(not isinstance(entry, ProviderMetadata) for entry in entries):
            raise ProviderRegistryError("registry entries must be ProviderMetadata")
        if len({entry.id for entry in entries}) != len(entries):
            raise ProviderRegistryError("duplicate provider id")
        if len({entry.credential_env for entry in entries}) != len(entries):
            raise ProviderRegistryError("duplicate credential environment name")
        object.__setattr__(self, "_entries", entries)

    @property
    def entries(self) -> tuple[ProviderMetadata, ...]:
        return self._entries

    def get(self, provider_id: str) -> ProviderMetadata:
        for entry in self._entries:
            if entry.id == provider_id:
                return entry
        raise ProviderRegistryError(f"unknown provider: {provider_id!r}")

    def for_capability(self, capability: str) -> tuple[ProviderMetadata, ...]:
        return tuple(entry for entry in self._entries if capability in entry.capabilities)

    def require_capability(self, provider_id: str, capability: str) -> ProviderMetadata:
        entry = self.get(provider_id)
        if capability not in entry.capabilities:
            raise ProviderRegistryError(
                f"provider {provider_id!r} does not support capability {capability!r}"
            )
        return entry


def default_provider_registry() -> ProviderRegistry:
    return ProviderRegistry(
        (
            ProviderMetadata(
                "openai",
                "OpenAI",
                "OPENAI_API_KEY",
                frozenset({TEXT_TO_SPEECH}),
            ),
            ProviderMetadata(
                "elevenlabs",
                "ElevenLabs / ElevenReader (UNTESTED)",
                "ELEVENLABS_API_KEY",
                frozenset({TEXT_TO_SPEECH}),
            ),
        )
    )


__all__ = [
    "TEXT_TO_SPEECH",
    "ProviderMetadata",
    "ProviderRegistry",
    "ProviderRegistryError",
    "default_provider_registry",
]
