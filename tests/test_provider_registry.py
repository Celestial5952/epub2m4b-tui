import pytest

from epub2m4b.providers.registry import (
    TEXT_TO_SPEECH,
    ProviderMetadata,
    ProviderRegistry,
    ProviderRegistryError,
    default_provider_registry,
)


def test_defaults_select_openai_and_elevenlabs_for_tts() -> None:
    registry = default_provider_registry()
    assert registry.get("openai").credential_env == "OPENAI_API_KEY"
    assert registry.get("elevenlabs").credential_env == "ELEVENLABS_API_KEY"
    assert registry.get("elevenlabs").display_name == (
        "ElevenLabs / ElevenReader (UNTESTED)"
    )
    assert registry.for_capability(TEXT_TO_SPEECH) == (
        registry.get("openai"),
        registry.get("elevenlabs"),
    )
    assert registry.require_capability("elevenlabs", TEXT_TO_SPEECH) == registry.get(
        "elevenlabs"
    )


def test_order_and_namespaces_are_stable() -> None:
    registry = default_provider_registry()
    assert tuple(entry.id for entry in registry.entries) == ("openai", "elevenlabs")
    assert tuple(entry.credential_env for entry in registry.entries) == (
        "OPENAI_API_KEY",
        "ELEVENLABS_API_KEY",
    )


def test_registry_and_metadata_are_immutable() -> None:
    metadata = default_provider_registry().get("openai")
    with pytest.raises((AttributeError, TypeError)):
        metadata.display_name = "changed"  # type: ignore[misc]
    registry = default_provider_registry()
    with pytest.raises((AttributeError, TypeError)):
        registry.entries += (metadata,)  # type: ignore[misc]
    with pytest.raises(AttributeError):
        metadata.capabilities.add("other")  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "metadata",
    [
        ProviderMetadata("safe", "Name", "SAFE_KEY", frozenset()),
    ],
)
def test_valid_empty_capabilities_are_allowed(metadata: ProviderMetadata) -> None:
    assert metadata.capabilities == frozenset()


def test_invalid_metadata_and_duplicates_are_rejected() -> None:
    with pytest.raises(ProviderRegistryError):
        ProviderMetadata("Bad ID", "Name", "SAFE_KEY", frozenset())
    with pytest.raises(ProviderRegistryError):
        ProviderMetadata("safe", "", "SAFE_KEY", frozenset())
    with pytest.raises(ProviderRegistryError):
        ProviderMetadata("safe", "Name", "not_upper", frozenset())
    with pytest.raises(ProviderRegistryError):
        ProviderMetadata("safe", "Name", "Ü_KEY", frozenset())
    with pytest.raises(ProviderRegistryError, match="entries"):
        ProviderRegistry((object(),))  # type: ignore[arg-type]
    first = ProviderMetadata("one", "One", "SAME_KEY", frozenset())
    second = ProviderMetadata("two", "Two", "SAME_KEY", frozenset())
    with pytest.raises(ProviderRegistryError, match="environment"):
        ProviderRegistry((first, second))
    with pytest.raises(ProviderRegistryError, match="id"):
        ProviderRegistry((first, ProviderMetadata("one", "Other", "OTHER_KEY", frozenset())))


def test_unknown_provider_does_not_invent_one() -> None:
    with pytest.raises(ProviderRegistryError, match="unknown provider"):
        default_provider_registry().get("google")
