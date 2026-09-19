from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA_VERSION = 1
_CREDENTIAL_OPTION_TERMS = (
    "apikey",
    "authorization",
    "credential",
    "header",
    "password",
    "secret",
    "token",
)


def _validate_generation_options(options: object) -> None:
    if not isinstance(options, dict):
        raise ValueError("generation options must be a dictionary")
    for key in options:
        if not isinstance(key, str):
            raise ValueError("generation option names must be strings")
        normalized = "".join(character for character in key.casefold() if character.isalnum())
        if any(term in normalized for term in _CREDENTIAL_OPTION_TERMS):
            raise ValueError("generation options must not contain credentials or headers")


class ChunkStatus(StrEnum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETE = "complete"
    FAILED = "failed"


class JobStatus(StrEnum):
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class Chapter:
    index: int
    title: str
    source_href: str | None
    html: str
    text: str
    included: bool = True

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("chapter index cannot be negative")


@dataclass(frozen=True, slots=True)
class BookMetadata:
    title: str
    authors: tuple[str, ...]
    language: str | None
    publisher: str | None
    publication_date: str | None
    identifier: str | None


@dataclass(frozen=True, slots=True)
class Book:
    source_path: Path
    source_sha256: str
    title: str
    authors: tuple[str, ...]
    language: str | None
    publisher: str | None
    publication_date: str | None
    identifier: str | None
    cover_path: Path | None
    chapters: tuple[Chapter, ...]


@dataclass(frozen=True, slots=True)
class NarrationSettings:
    provider: str
    model: str
    voice: str
    speed: float
    instructions: str
    generation_options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("provider is required")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("model is required")
        if not isinstance(self.voice, str) or not self.voice.strip():
            raise ValueError("voice is required")
        if (
            isinstance(self.speed, bool)
            or not isinstance(self.speed, (int, float))
            or not math.isfinite(self.speed)
            or self.speed <= 0
        ):
            raise ValueError("speed must be greater than zero")
        if not isinstance(self.instructions, str):
            raise ValueError("instructions must be a string")
        _validate_generation_options(self.generation_options)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def generation_hash(text: str, settings: NarrationSettings) -> str:
    payload = {
        "generation_options": settings.generation_options,
        "instructions": settings.instructions,
        "model": settings.model,
        "provider": settings.provider,
        "speed": format(settings.speed, ".12g"),
        "text": text,
        "voice": settings.voice,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Chunk:
    chapter_index: int
    chunk_index: int
    text: str
    text_hash: str
    generation_hash: str
    status: ChunkStatus = ChunkStatus.PENDING
    attempt_count: int = 0
    audio_path: str | None = None
    duration_seconds: float | None = None
    generated_at: str | None = None
    last_error: str | None = None

    @property
    def id(self) -> str:
        return (
            f"chapter-{self.chapter_index + 1:03d}_"
            f"chunk-{self.chunk_index + 1:03d}_{self.generation_hash[:12]}"
        )

    @classmethod
    def create(
        cls,
        *,
        chapter_index: int,
        chunk_index: int,
        text: str,
        settings: NarrationSettings,
    ) -> Chunk:
        if chapter_index < 0 or chunk_index < 0:
            raise ValueError("chapter and chunk indexes cannot be negative")
        if not text:
            raise ValueError("chunk text cannot be empty")
        return cls(
            chapter_index=chapter_index,
            chunk_index=chunk_index,
            text=text,
            text_hash=sha256_text(text),
            generation_hash=generation_hash(text, settings),
        )


@dataclass(frozen=True, slots=True)
class ManifestSource:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ManifestBook:
    title: str
    authors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class JobManifest:
    job_id: str
    app_version: str
    source: ManifestSource
    book: ManifestBook
    narration: NarrationSettings
    chunks: tuple[Chunk, ...]
    status: JobStatus = JobStatus.READY
    schema_version: int = MANIFEST_SCHEMA_VERSION
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"unsupported manifest schema version: {self.schema_version}")
        if not self.job_id.strip():
            raise ValueError("job ID is required")
