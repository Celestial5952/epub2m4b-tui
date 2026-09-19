from __future__ import annotations

from dataclasses import dataclass

import pytest

from epub2m4b.credentials import SERVICE_NAME, Credential, CredentialService
from epub2m4b.exceptions import CredentialError


@dataclass
class FakeKeyring:
    values: dict[tuple[str, str], str] | None = None
    fail: Exception | None = None

    def __post_init__(self) -> None:
        if self.values is None:
            self.values = {}

    def get_password(self, service: str, username: str) -> str | None:
        if self.fail:
            raise self.fail
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        if self.fail:
            raise self.fail
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.fail:
            raise self.fail
        self.values.pop((service, username), None)


def test_provider_namespaces_are_separate() -> None:
    keyring = FakeKeyring()
    service = CredentialService(keyring)
    service.set("openai", "openai-secret")
    service.set("elevenlabs", "elevenlabs-secret")

    assert keyring.values == {
        (SERVICE_NAME, "openai"): "openai-secret",
        (SERVICE_NAME, "elevenlabs"): "elevenlabs-secret",
    }
    assert service.get("openai", {}) == Credential("openai-secret", "keyring")
    assert service.get("elevenlabs", {}) == Credential("elevenlabs-secret", "keyring")


def test_environment_precedes_keyring_and_status_redacts_value() -> None:
    keyring = FakeKeyring({(SERVICE_NAME, "openai"): "stored-secret"})
    service = CredentialService(keyring)

    credential = service.get("openai", {"OPENAI_API_KEY": " env-secret "})

    assert credential == Credential(" env-secret ", "environment")
    assert service.status("openai", {"OPENAI_API_KEY": " env-secret "}) == "environment"
    assert "env-secret" not in repr(credential)
    assert "env-secret" not in str(credential)


def test_omitted_environment_uses_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    keyring = FakeKeyring({(SERVICE_NAME, "openai"): "stored-secret"})
    service = CredentialService(keyring)
    monkeypatch.setenv("OPENAI_API_KEY", "process-secret")

    assert service.get("openai") == Credential("process-secret", "environment")
    assert service.status("openai") == "environment"


def test_missing_and_blank_values_are_unconfigured() -> None:
    service = CredentialService(FakeKeyring({(SERVICE_NAME, "openai"): "  "}))
    assert service.get("openai", {"OPENAI_API_KEY": "\t"}) is None
    assert service.status("openai", {}) == "unconfigured"


@pytest.mark.parametrize("provider", ["", "google", " OpenAI", None])
def test_unknown_provider_is_rejected(provider: str | None) -> None:
    service = CredentialService(FakeKeyring())
    with pytest.raises(CredentialError, match="unknown provider"):
        service.status(provider)  # type: ignore[arg-type]


@pytest.mark.parametrize("secret", ["", " ", "\n\t", None])
def test_set_requires_nonblank_secret(secret: str | None) -> None:
    service = CredentialService(FakeKeyring())
    with pytest.raises(CredentialError, match="nonblank"):
        service.set("openai", secret)  # type: ignore[arg-type]


def test_set_and_delete_only_touch_named_entry() -> None:
    keyring = FakeKeyring({(SERVICE_NAME, "elevenlabs"): "keep"})
    service = CredentialService(keyring)
    service.set("openai", "new")
    service.delete("openai")
    assert keyring.values == {(SERVICE_NAME, "elevenlabs"): "keep"}


def test_delete_is_idempotent_when_provider_has_no_saved_key() -> None:
    service = CredentialService(FakeKeyring())

    service.delete("openai")

    assert service.status("openai", {}) == "unconfigured"


@pytest.mark.parametrize("operation", ["get", "status", "set", "delete"])
def test_backend_failures_are_generic(operation: str) -> None:
    secret = "do-not-leak"
    service = CredentialService(FakeKeyring(fail=RuntimeError(f"backend {secret}")))
    with pytest.raises(CredentialError) as raised:
        if operation == "get":
            service.get("openai", {})
        elif operation == "status":
            service.status("openai", {})
        elif operation == "set":
            service.set("openai", secret)
        else:
            service.delete("openai")
    assert secret not in str(raised.value)
    assert secret not in repr(raised.value)
    assert raised.value.__suppress_context__ is True
    assert raised.value.__cause__ is None


def test_import_failure_becomes_credential_error(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = __import__("importlib").import_module

    def fail(name: str) -> object:
        if name == "keyring":
            raise ImportError("missing keyring")
        return real_import(name)

    monkeypatch.setattr("epub2m4b.credentials.importlib.import_module", fail)
    with pytest.raises(CredentialError, match="failed"):
        CredentialService().status("openai", {})
