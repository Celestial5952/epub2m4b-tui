"""Provider credential access through environment variables and keyring."""

from __future__ import annotations

import importlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from .exceptions import CredentialError

SERVICE_NAME = "epub2m4b"
_PROVIDER_ENV = {"openai": "OPENAI_API_KEY", "elevenlabs": "ELEVENLABS_API_KEY"}


class _KeyringBackend(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


@dataclass(frozen=True, slots=True, repr=False)
class Credential:
    """A credential value and its origin.

    The value is available only to the credential boundary; textual
    representations intentionally never include it.
    """

    secret: str
    source: str

    def __repr__(self) -> str:
        return f"Credential(secret=<redacted>, source={self.source!r})"

    def __str__(self) -> str:
        return f"Credential(<redacted>, source={self.source})"


class CredentialService:
    """Resolve provider credentials without persisting them in application files."""

    def __init__(self, backend: _KeyringBackend | None = None) -> None:
        self._backend = backend
        self._backend_loaded = backend is not None

    @staticmethod
    def _env_for(provider_id: str) -> str:
        if not isinstance(provider_id, str) or provider_id not in _PROVIDER_ENV:
            raise CredentialError("unknown provider")
        return _PROVIDER_ENV[provider_id]

    @staticmethod
    def _env_value(env: Mapping[str, str] | None, name: str) -> str | None:
        if env is None:
            return None
        try:
            value = env.get(name)
        except Exception:
            raise CredentialError("credential environment is unavailable") from None
        if value is not None and not isinstance(value, str):
            raise CredentialError("credential environment is invalid") from None
        return value if value and value.strip() else None

    def _keyring(self) -> _KeyringBackend:
        if self._backend_loaded:
            # The assignment is guaranteed by __init__ when this flag is true.
            return cast(_KeyringBackend, self._backend)
        try:
            self._backend = cast(_KeyringBackend, importlib.import_module("keyring"))
            self._backend_loaded = True
            return self._backend
        except Exception:
            raise CredentialError("credential backend is unavailable") from None

    def get(self, provider_id: str, env: Mapping[str, str] | None = None) -> Credential | None:
        env_name = self._env_for(provider_id)
        environment_secret = self._env_value(os.environ if env is None else env, env_name)
        if environment_secret is not None:
            return Credential(environment_secret, "environment")
        try:
            secret = self._keyring().get_password(SERVICE_NAME, provider_id)
        except Exception:
            raise CredentialError("credential backend operation failed") from None
        if secret is None or (isinstance(secret, str) and not secret.strip()):
            return None
        if not isinstance(secret, str):
            raise CredentialError("credential backend returned invalid data") from None
        return Credential(secret, "keyring")

    def status(self, provider_id: str, env: Mapping[str, str] | None = None) -> str:
        env_name = self._env_for(provider_id)
        if self._env_value(os.environ if env is None else env, env_name) is not None:
            return "environment"
        try:
            secret = self._keyring().get_password(SERVICE_NAME, provider_id)
        except Exception:
            raise CredentialError("credential backend operation failed") from None
        if secret is None or (isinstance(secret, str) and not secret.strip()):
            return "unconfigured"
        if not isinstance(secret, str):
            raise CredentialError("credential backend returned invalid data") from None
        return "configured"

    def set(self, provider_id: str, secret: str) -> None:
        self._env_for(provider_id)
        if not isinstance(secret, str) or not secret.strip():
            raise CredentialError("credential must be nonblank")
        try:
            self._keyring().set_password(SERVICE_NAME, provider_id, secret)
        except Exception:
            raise CredentialError("credential backend operation failed") from None

    def delete(self, provider_id: str) -> None:
        self._env_for(provider_id)
        try:
            backend = self._keyring()
            existing = backend.get_password(SERVICE_NAME, provider_id)
            if existing is None or (isinstance(existing, str) and not existing.strip()):
                return
            backend.delete_password(SERVICE_NAME, provider_id)
        except Exception:
            raise CredentialError("credential backend operation failed") from None


__all__ = ["Credential", "CredentialError", "CredentialService", "SERVICE_NAME"]
