"""Durable audit trail for paid provider activity and money boundaries.

Every entry is one JSON object on its own line. Appends are a single write to
an ``O_APPEND`` file followed by ``fsync``, so a crash can never leave a torn
record. The log is append-only and bounded: when the primary file grows past
``max_bytes`` it is atomically renamed to ``audit.jsonl.1`` and a fresh primary
is started. Credential material is never written; free-text messages are
length-capped and API-key-shaped tokens are redacted before persistence.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from epub2m4b.providers.base import SynthesisRequest, SynthesisResult, TTSProvider

# Entry kinds.
REQUEST = "request"
SUCCESS = "success"
FAILURE = "failure"
ESTIMATE = "estimate"
AUTHORIZED = "authorized"
CACHED = "cached"
COMPLETE = "complete"
PAUSED = "paused"
CANCELLED = "cancelled"
ASSEMBLY = "assembly"
JOB = "job"
CREDENTIAL = "credential"
CONNECTION = "connection"

_ENTRY_KEYS = frozenset(
    {
        "timestamp",
        "kind",
        "provider",
        "job_id",
        "request_id",
        "model",
        "voice",
        "characters",
        "message",
    }
)

_MAX_MESSAGE = 240
_API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{6,}")
_AUTHORIZATION_PATTERN = re.compile(r"(?i)authorization\s*:\s*[^\r\n;]+")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def _clip(text: str, limit: int = _MAX_MESSAGE) -> str:
    cleaned = _WHITESPACE_PATTERN.sub(" ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _sanitize(text: str) -> str:
    """Redact API-key-shaped tokens and bound free-text length."""

    return _clip(
        _API_KEY_PATTERN.sub(
            "sk-<redacted>", _AUTHORIZATION_PATTERN.sub("Authorization: <redacted>", text)
        )
    )


def sanitize(text: str) -> str:
    """Public redaction used before writing free-text errors to the audit log."""

    return _sanitize(text)


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One immutable audit record; never carries credential material."""

    timestamp: str
    kind: str
    message: str
    provider: str | None = None
    job_id: str | None = None
    request_id: str | None = None
    model: str | None = None
    voice: str | None = None
    characters: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "kind": self.kind,
            "provider": self.provider,
            "job_id": self.job_id,
            "request_id": self.request_id,
            "model": self.model,
            "voice": self.voice,
            "characters": self.characters,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AuditEntry:
        unknown = set(payload) - _ENTRY_KEYS
        if unknown:
            raise ValueError(f"unknown audit entry fields: {sorted(unknown)}")
        timestamp = payload.get("timestamp")
        kind = payload.get("kind")
        message = payload.get("message")
        if not isinstance(timestamp, str) or not isinstance(kind, str):
            raise ValueError("audit entry requires string timestamp and kind")
        characters = payload.get("characters")
        return cls(
            timestamp=timestamp,
            kind=kind,
            message=message if isinstance(message, str) else "",
            provider=_optional_str(payload.get("provider")),
            job_id=_optional_str(payload.get("job_id")),
            request_id=_optional_str(payload.get("request_id")),
            model=_optional_str(payload.get("model")),
            voice=_optional_str(payload.get("voice")),
            characters=characters if isinstance(characters, int) else None,
        )


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


class AuditLog:
    """Append-only, fsync'd, size-bounded JSONL audit log."""

    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = 1_000_000,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be greater than zero")
        self.path = Path(path)
        self.max_bytes = max_bytes
        self._now = now or (lambda: datetime.now(UTC))

    @property
    def backup_path(self) -> Path:
        return self.path.with_name(f"{self.path.name}.1")

    def record(
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
    ) -> AuditEntry:
        entry = AuditEntry(
            timestamp=self._now().isoformat(),
            kind=kind,
            message=_clip(message),
            provider=provider,
            job_id=job_id,
            request_id=request_id,
            model=model,
            voice=voice,
            characters=characters,
        )
        self.append(entry)
        return entry

    def append(self, entry: AuditEntry) -> None:
        """Persist one entry atomically on its own line."""

        line = json.dumps(entry.to_dict(), sort_keys=True, ensure_ascii=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._rotate_if_needed()

    def _rotate_if_needed(self) -> None:
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size <= self.max_bytes:
            return
        os.replace(self.path, self.backup_path)

    def entries(self, limit: int = 200) -> tuple[AuditEntry, ...]:
        """Return up to ``limit`` entries, newest first, tolerating damage."""

        if limit <= 0:
            return ()
        rows: list[AuditEntry] = []
        for source in (self.backup_path, self.path):
            rows.extend(self._read_file(source))
        rows.sort(key=lambda entry: entry.timestamp)
        newest = rows[len(rows) - limit :] if len(rows) > limit else rows
        newest.reverse()
        return tuple(newest)

    @staticmethod
    def _read_file(path: Path) -> list[AuditEntry]:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            return []
        rows: list[AuditEntry] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(AuditEntry.from_dict(payload))
            except (ValueError, TypeError):
                continue
        return rows


class AuditedTTSProvider:
    """Log every paid synthesis request, success, and failure.

    Logging failures are suppressed so an audit problem can never interrupt
    or corrupt paid narration; the underlying provider is untouched.
    """

    def __init__(
        self,
        provider: TTSProvider,
        audit: AuditLog,
        *,
        job_id: str | None = None,
    ) -> None:
        self._provider = provider
        self._audit = audit
        self._job_id = job_id

    @property
    def name(self) -> str:
        return self._provider.name

    async def synthesize(
        self,
        request: SynthesisRequest,
        destination: Path,
    ) -> SynthesisResult:
        started = time.monotonic()

        def elapsed() -> str:
            return f"{time.monotonic() - started:.1f}s"

        with suppress(Exception):
            self._audit.record(
                REQUEST,
                "provider synthesis request started",
                provider=self.name,
                job_id=self._job_id,
                request_id=request.request_id,
                model=request.model,
                voice=request.voice,
                characters=len(request.text),
            )
        try:
            result = await self._provider.synthesize(request, destination)
        except Exception as exc:
            with suppress(Exception):
                self._audit.record(
                    FAILURE,
                    f"{type(exc).__name__}: {_sanitize(str(exc))} "
                    f"(attempt failed after {elapsed()})",
                    provider=self.name,
                    job_id=self._job_id,
                    request_id=request.request_id,
                    model=request.model,
                    voice=request.voice,
                    characters=len(request.text),
                )
            raise
        detail = (
            f" (provider request id: {result.provider_request_id})"
            if result.provider_request_id
            else ""
        )
        with suppress(Exception):
            self._audit.record(
                SUCCESS,
                f"provider synthesis succeeded in {elapsed()}{detail}",
                provider=self.name,
                job_id=self._job_id,
                request_id=result.request_id or request.request_id,
                model=request.model,
                voice=request.voice,
                characters=len(request.text),
            )
        return result


__all__ = [
    "ASSEMBLY",
    "AUTHORIZED",
    "CACHED",
    "CANCELLED",
    "COMPLETE",
    "CREDENTIAL",
    "CONNECTION",
    "ESTIMATE",
    "FAILURE",
    "JOB",
    "PAUSED",
    "REQUEST",
    "SUCCESS",
    "AuditedTTSProvider",
    "AuditEntry",
    "AuditLog",
    "sanitize",
]
