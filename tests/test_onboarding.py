from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from epub2m4b.app.onboarding import OnboardingService, ProviderOption, provider_options
from epub2m4b.config import AppConfig
from epub2m4b.config_store import ConfigRepository
from epub2m4b.credentials import CredentialError
from epub2m4b.providers.registry import TEXT_TO_SPEECH, ProviderMetadata, ProviderRegistry


@dataclass(frozen=True, slots=True)
class Voice:
    id: str
    display_name: str


class Registry:
    def __init__(self, *entries: Voice) -> None:
        self.entries = tuple(entries)
        self._by_id = {entry.id: entry for entry in self.entries}

    def get(self, voice_id: str) -> Voice:
        try:
            return self._by_id[voice_id]
        except KeyError as exc:
            raise KeyError(voice_id) from exc


class Credentials:
    def __init__(self, status: str = "unconfigured") -> None:
        self.status_value = status
        self.calls: list[tuple[str, str, object]] = []

    def status(self, provider: str, env: Mapping[str, str] | None = None) -> str:
        self.calls.append(("status", provider, env))
        return self.status_value

    def set(self, provider: str, secret: str) -> None:
        self.calls.append(("set", provider, secret))

    def delete(self, provider: str) -> None:
        self.calls.append(("delete", provider, None))


class UnavailableCredentials(Credentials):
    def status(self, provider: str, env: Mapping[str, str] | None = None) -> str:
        raise CredentialError("backend failed with secret_should_not_escape")


def make_service(
    tmp_path: Path, credentials: object | None = None
) -> tuple[OnboardingService, Registry, Path]:
    path = tmp_path / "config.toml"
    registry = Registry(Voice("marin", "Marin"), Voice("nova", "Nova"))
    service = OnboardingService(
        path,
        credentials or Credentials(),
        registry,
        lambda: ("ffmpeg", "ffprobe", "ffplay"),
    )
    return service, registry, path


def test_initial_state_is_local_and_unconfigured(tmp_path: Path) -> None:
    service, registry, path = make_service(tmp_path)
    state = service.state({})
    assert state.completed is False
    assert state.selected_voice == AppConfig().voice
    assert state.credential_status == "unconfigured"
    assert state.dependencies == ("ffmpeg", "ffprobe", "ffplay")
    assert state.voices == registry.entries
    assert not path.exists()


def test_complete_persists_selection_and_preserves_other_settings(tmp_path: Path) -> None:
    service, _, path = make_service(tmp_path)
    original = AppConfig(
        model="local-model",
        voice="marin",
        speed=1.25,
        instructions="Read exactly.",
        cache_directory=tmp_path / "cache",
        book_directory=tmp_path / "books",
        output_directory=tmp_path / "output",
        work_directory=tmp_path / "work",
        concurrency=4,
        aac_bitrate_kbps=128,
        maximum_estimated_cost_usd=3.5,
        generation_options={"format": "wav"},
    )
    ConfigRepository.save(path, original)
    service.complete("nova")
    saved = ConfigRepository.load(path)
    assert saved.onboarding_complete is True
    assert saved.voice == "nova"
    assert saved.model == original.model
    assert saved.speed == original.speed
    assert saved.instructions == original.instructions
    assert saved.cache_directory == original.cache_directory
    assert saved.book_directory == original.book_directory
    assert saved.output_directory == original.output_directory
    assert saved.work_directory == original.work_directory
    assert saved.concurrency == original.concurrency
    assert saved.aac_bitrate_kbps == original.aac_bitrate_kbps
    assert saved.maximum_estimated_cost_usd == original.maximum_estimated_cost_usd
    assert saved.generation_options == original.generation_options


def test_invalid_voice_does_not_write(tmp_path: Path) -> None:
    service, _, path = make_service(tmp_path)
    original = AppConfig(onboarding_complete=False, voice="marin")
    ConfigRepository.save(path, original)
    before = path.read_bytes()
    with pytest.raises(KeyError):
        service.complete("does-not-exist")
    assert path.read_bytes() == before
    assert ConfigRepository.load(path) == original


def test_skip_marks_complete_and_preserves_voice_and_settings(tmp_path: Path) -> None:
    service, _, path = make_service(tmp_path)
    original = AppConfig(voice="nova", speed=0.8, generation_options={"x": "y"})
    ConfigRepository.save(path, original)
    service.skip()
    saved = ConfigRepository.load(path)
    assert saved.onboarding_complete is True
    assert saved.voice == "nova"
    assert saved.speed == original.speed
    assert saved.generation_options == original.generation_options


def test_credential_operations_delegate_without_provider_access(tmp_path: Path) -> None:
    credentials = Credentials()
    service, _, _ = make_service(tmp_path, credentials)
    service.set_credential("secret-value")
    service.remove_credential()
    assert credentials.calls == [("set", "openai", "secret-value"), ("delete", "openai", None)]


def test_unavailable_credential_backend_is_redacted(tmp_path: Path) -> None:
    service, _, _ = make_service(tmp_path, UnavailableCredentials())
    state = service.state({})
    assert state.credential_status == "unavailable"
    assert "secret_should_not_escape" not in repr(state)


def test_state_never_needs_a_provider_or_network(tmp_path: Path) -> None:
    calls: list[str] = []
    service, _, _ = make_service(tmp_path)
    service._dependency_checker = lambda: calls.append("checked") or ()  # type: ignore[attr-defined]
    state = service.state({"OPENAI_API_KEY": "ignored-by-status-fake"})
    assert state.dependencies == ()
    assert calls == ["checked"]


def test_state_migrates_retired_openai_model_before_a_job_can_be_created(tmp_path: Path) -> None:
    service, _, path = make_service(tmp_path)
    ConfigRepository.save(path, AppConfig(onboarding_complete=True, model="gpt-4o-tts"))

    state = service.state({})

    assert state.model == "gpt-4o-mini-tts"
    assert ConfigRepository.load(path).model == "gpt-4o-mini-tts"


def test_state_exposes_storage_defaults_without_creating_them(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    registry = Registry(Voice("marin", "Marin"))
    cache = tmp_path / "default-cache"
    books = tmp_path / "default-books"
    service = OnboardingService(
        config_path,
        Credentials(),
        registry,
        lambda: (),
        default_cache_directory=cache,
        default_book_directory=books,
    )

    state = service.state({})

    assert state.cache_directory == cache
    assert state.book_directory == books
    assert not cache.exists()
    assert not books.exists()


def test_complete_persists_valid_storage_and_creates_cache(tmp_path: Path) -> None:
    service, _, path = make_service(tmp_path)
    cache = tmp_path / "new-cache"
    books = tmp_path / "library"
    books.mkdir()

    service.complete("nova", cache, books)

    saved = ConfigRepository.load(path)
    assert saved.cache_directory == cache.resolve()
    assert saved.book_directory == books.resolve()
    assert cache.is_dir()


@pytest.mark.parametrize("which", ["cache", "books"])
def test_invalid_storage_does_not_change_configuration(tmp_path: Path, which: str) -> None:
    service, _, path = make_service(tmp_path)
    original = AppConfig(voice="marin")
    ConfigRepository.save(path, original)
    cache = tmp_path / "cache"
    books = tmp_path / "books"
    books.mkdir()
    if which == "cache":
        cache = Path("relative-cache")
    else:
        books = tmp_path / "missing-books"

    with pytest.raises(ValueError):
        service.complete("nova", cache, books)

    assert ConfigRepository.load(path) == original


def test_complete_persists_output_directory_and_creates_it(tmp_path: Path) -> None:
    service, _, path = make_service(tmp_path)
    output = tmp_path / " Audiobooks "

    service.complete("marin", output_directory=output)

    saved = ConfigRepository.load(path)
    assert saved.output_directory == output.resolve()
    assert output.is_dir()


def test_invalid_output_directory_does_not_change_configuration(tmp_path: Path) -> None:
    service, _, path = make_service(tmp_path)
    original = AppConfig(voice="marin")
    ConfigRepository.save(path, original)

    with pytest.raises(ValueError):
        service.complete("marin", output_directory=Path("relative-output"))

    assert ConfigRepository.load(path) == original


def test_complete_persists_narration_and_spending_settings(tmp_path: Path) -> None:
    service, _, path = make_service(tmp_path)

    service.complete(
        "marin",
        provider="openai",
        model="gpt-4o-mini-tts",
        speed=1.1,
        instructions="Read slowly.",
        maximum_estimated_cost_usd=30.0,
    )

    saved = ConfigRepository.load(path)
    assert saved.provider == "openai"
    assert saved.model == "gpt-4o-mini-tts"
    assert saved.speed == 1.1
    assert saved.instructions == "Read slowly."
    assert saved.maximum_estimated_cost_usd == 30.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"speed": 0.0},
        {"speed": float("inf")},
        {"maximum_estimated_cost_usd": -1.0},
        {"model": " "},
        {"provider": " "},
    ],
)
def test_invalid_narration_settings_do_not_write(
    tmp_path: Path, kwargs: dict[str, object]
) -> None:
    service, _, path = make_service(tmp_path)
    original = AppConfig(voice="marin")
    ConfigRepository.save(path, original)

    with pytest.raises(ValueError):
        service.complete("marin", **kwargs)

    assert ConfigRepository.load(path) == original


def test_complete_omitted_options_preserve_previous_values(tmp_path: Path) -> None:
    service, _, path = make_service(tmp_path)
    previous = AppConfig(
        voice="nova",
        model="gpt-4o-mini-tts",
        speed=1.2,
        instructions="Previous.",
        maximum_estimated_cost_usd=12.0,
        output_directory=tmp_path / "out",
    )
    ConfigRepository.save(path, previous)

    service.complete("marin")

    saved = ConfigRepository.load(path)
    assert saved.voice == "marin"
    assert saved.model == previous.model
    assert saved.speed == previous.speed
    assert saved.instructions == previous.instructions
    assert saved.maximum_estimated_cost_usd == previous.maximum_estimated_cost_usd
    assert saved.output_directory == previous.output_directory


class PerProviderCredentials(Credentials):
    def __init__(self, statuses: dict[str, str]) -> None:
        super().__init__()
        self.statuses = statuses

    def status(self, provider: str, env: Mapping[str, str] | None = None) -> str:
        self.calls.append(("status", provider, env))
        return self.statuses[provider]


def test_state_lists_every_registry_provider_with_its_own_key_status(tmp_path: Path) -> None:
    credentials = PerProviderCredentials({"openai": "configured", "elevenlabs": "environment"})
    service, _, _ = make_service(tmp_path, credentials)

    state = service.state({})

    assert [option.id for option in state.providers] == ["openai", "elevenlabs"]
    openai, elevenlabs = state.providers
    assert (openai.name, openai.label, openai.live_verified) == (
        "OpenAI",
        "OpenAI (verified)",
        True,
    )
    assert (elevenlabs.label, elevenlabs.live_verified) == (
        "ElevenLabs (UNTESTED live)",
        False,
    )
    assert (openai.credential_status, elevenlabs.credential_status) == (
        "configured",
        "environment",
    )
    assert elevenlabs.credential_env == "ELEVENLABS_API_KEY"
    assert elevenlabs.key_url.startswith("https://")
    # The older per-provider fields stay populated for existing callers.
    assert state.credential_status == "configured"
    assert state.elevenlabs_credential_status == "environment"


def test_one_provider_with_an_unavailable_keyring_does_not_hide_the_others(
    tmp_path: Path,
) -> None:
    class Flaky(PerProviderCredentials):
        def status(self, provider: str, env: Mapping[str, str] | None = None) -> str:
            if provider == "openai":
                raise CredentialError("backend failed with secret_should_not_escape")
            return super().status(provider, env)

    service, _, _ = make_service(tmp_path, Flaky({"elevenlabs": "configured"}))
    openai, elevenlabs = service.state({}).providers
    assert openai.credential_status == "unavailable"
    assert elevenlabs.credential_status == "configured"
    assert "secret_should_not_escape" not in repr(service.state({}))


def test_registry_added_provider_appears_in_state_without_code_changes(tmp_path: Path) -> None:
    acme = ProviderMetadata(
        "acme",
        "Acme Voice",
        "ACME_API_KEY",
        frozenset({TEXT_TO_SPEECH}),
        key_url="https://acme.example/keys",
        default_model="acme-1",
        live_verified=True,
    )
    other = ProviderMetadata("stt", "Transcribe", "STT_API_KEY", frozenset({"speech_to_text"}))
    registry = ProviderRegistry((acme, other))
    credentials = PerProviderCredentials({"acme": "unconfigured"})
    path = tmp_path / "config.toml"
    service = OnboardingService(
        path,
        credentials,
        Registry(Voice("marin", "Marin")),
        lambda: (),
        registry=registry,
    )

    state = service.state({})

    # Only text-to-speech providers are offered for narration.
    assert [option.id for option in state.providers] == ["acme"]
    assert state.providers[0].default_model == "acme-1"
    service.complete("marin", provider="acme", model="acme-1")
    assert ConfigRepository.load(path).provider == "acme"


def test_provider_options_defaults_to_the_registry_with_unconfigured_keys() -> None:
    options = provider_options()
    assert [option.id for option in options] == ["openai", "elevenlabs"]
    assert {option.credential_status for option in options} == {"unconfigured"}
    assert isinstance(options[0], ProviderOption)


def test_generic_credential_methods_delegate_for_any_provider(tmp_path: Path) -> None:
    credentials = Credentials()
    service, _, _ = make_service(tmp_path, credentials)

    service.set_provider_credential("elevenlabs", "el-secret")
    service.remove_provider_credential("elevenlabs")
    # The older per-provider methods are thin wrappers over the generic ones.
    service.set_credential("oa-secret")
    service.remove_credential()
    service.set_elevenlabs_credential("el-secret-2")
    service.remove_elevenlabs_credential()

    assert credentials.calls == [
        ("set", "elevenlabs", "el-secret"),
        ("delete", "elevenlabs", None),
        ("set", "openai", "oa-secret"),
        ("delete", "openai", None),
        ("set", "elevenlabs", "el-secret-2"),
        ("delete", "elevenlabs", None),
    ]


def test_only_a_verified_registered_provider_can_become_the_narration_provider(
    tmp_path: Path,
) -> None:
    service, _, path = make_service(tmp_path)

    with pytest.raises(ValueError, match="UNTESTED"):
        service.complete("marin", provider="elevenlabs")
    with pytest.raises(ValueError, match="unknown narration provider"):
        service.complete("marin", provider="google")
    assert not path.exists()  # a refused selection never writes configuration

    service.complete("marin", provider="openai")
    assert ConfigRepository.load(path).provider == "openai"
