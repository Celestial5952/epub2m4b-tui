"""Durable JSON persistence for generation job manifests."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

from epub2m4b.exceptions import ManifestError, UnsupportedManifestVersionError
from epub2m4b.models import (
    MANIFEST_SCHEMA_VERSION,
    Chunk,
    ChunkStatus,
    JobManifest,
    JobStatus,
    ManifestBook,
    ManifestSource,
    NarrationSettings,
    _validate_generation_options,
)


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestError(f"manifest field {name!r} must be an object")
    return value


def _required(mapping: Mapping[str, Any], name: str) -> Any:
    if name not in mapping:
        raise ManifestError(f"manifest field {name!r} is missing")
    return mapping[name]


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ManifestError(f"manifest field {name!r} must be a string")
    return value


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _string(value, name)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(f"manifest field {name!r} must be an integer")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"manifest field {name!r} must be a number")
    return float(value)


def _authors(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(author, str) for author in value):
        raise ManifestError("manifest field 'authors' must be an array of strings")
    return tuple(value)


def _chunk(value: object) -> Chunk:
    data = _mapping(value, "chunks[]")
    try:
        return Chunk(
            chapter_index=_integer(_required(data, "chapter_index"), "chapter_index"),
            chunk_index=_integer(_required(data, "chunk_index"), "chunk_index"),
            text=_string(_required(data, "text"), "text"),
            text_hash=_string(_required(data, "text_hash"), "text_hash"),
            generation_hash=_string(_required(data, "generation_hash"), "generation_hash"),
            status=ChunkStatus(_string(data.get("status", ChunkStatus.PENDING), "status")),
            attempt_count=_integer(data.get("attempt_count", 0), "attempt_count"),
            audio_path=_optional_string(data.get("audio_path"), "audio_path"),
            duration_seconds=(
                None
                if data.get("duration_seconds") is None
                else _number(data["duration_seconds"], "duration_seconds")
            ),
            generated_at=_optional_string(data.get("generated_at"), "generated_at"),
            last_error=_optional_string(data.get("last_error"), "last_error"),
        )
    except (ValueError, TypeError) as exc:
        raise ManifestError("invalid chunk in manifest") from exc


def _from_data(data: object) -> JobManifest:
    root = _mapping(data, "manifest")
    version = _required(root, "schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ManifestError("manifest field 'schema_version' must be an integer")
    if version != MANIFEST_SCHEMA_VERSION:
        raise UnsupportedManifestVersionError(f"unsupported manifest schema version: {version}")

    source = _mapping(_required(root, "source"), "source")
    book = _mapping(_required(root, "book"), "book")
    narration = _mapping(_required(root, "narration"), "narration")
    chunks_value = _required(root, "chunks")
    if not isinstance(chunks_value, list):
        raise ManifestError("manifest field 'chunks' must be an array")
    options = narration.get("generation_options", {})
    if not isinstance(options, dict):
        raise ManifestError("manifest field 'generation_options' must be an object")

    try:
        return JobManifest(
            job_id=_string(_required(root, "job_id"), "job_id"),
            app_version=_string(_required(root, "app_version"), "app_version"),
            source=ManifestSource(
                path=_string(_required(source, "path"), "source.path"),
                sha256=_string(_required(source, "sha256"), "source.sha256"),
            ),
            book=ManifestBook(
                title=_string(_required(book, "title"), "book.title"),
                authors=_authors(_required(book, "authors")),
            ),
            narration=NarrationSettings(
                provider=_string(_required(narration, "provider"), "narration.provider"),
                model=_string(_required(narration, "model"), "narration.model"),
                voice=_string(_required(narration, "voice"), "narration.voice"),
                speed=_number(_required(narration, "speed"), "narration.speed"),
                instructions=_string(
                    _required(narration, "instructions"), "narration.instructions"
                ),
                generation_options=dict(options),
            ),
            chunks=tuple(_chunk(chunk) for chunk in chunks_value),
            status=JobStatus(_string(root.get("status", JobStatus.READY), "status")),
            schema_version=version,
            created_at=_optional_string(root.get("created_at"), "created_at"),
            updated_at=_optional_string(root.get("updated_at"), "updated_at"),
        )
    except (ValueError, TypeError) as exc:
        raise ManifestError("invalid manifest fields") from exc


def _data(manifest: JobManifest) -> dict[str, Any]:
    try:
        _validate_generation_options(manifest.narration.generation_options)
    except ValueError as exc:
        raise ManifestError("manifest generation options contain credentials or headers") from exc
    return {
        "app_version": manifest.app_version,
        "book": {"authors": list(manifest.book.authors), "title": manifest.book.title},
        "chunks": [
            {
                "attempt_count": chunk.attempt_count,
                "audio_path": chunk.audio_path,
                "chapter_index": chunk.chapter_index,
                "chunk_index": chunk.chunk_index,
                "duration_seconds": chunk.duration_seconds,
                "generated_at": chunk.generated_at,
                "generation_hash": chunk.generation_hash,
                "last_error": chunk.last_error,
                "status": chunk.status.value,
                "text": chunk.text,
                "text_hash": chunk.text_hash,
            }
            for chunk in manifest.chunks
        ],
        "created_at": manifest.created_at,
        "job_id": manifest.job_id,
        "narration": {
            "generation_options": manifest.narration.generation_options,
            "instructions": manifest.narration.instructions,
            "model": manifest.narration.model,
            "provider": manifest.narration.provider,
            "speed": manifest.narration.speed,
            "voice": manifest.narration.voice,
        },
        "schema_version": manifest.schema_version,
        "source": {"path": manifest.source.path, "sha256": manifest.source.sha256},
        "status": manifest.status.value,
        "updated_at": manifest.updated_at,
    }


class ManifestRepository:
    """Load and atomically save schema-versioned job manifests."""

    @staticmethod
    def load(path: Path) -> JobManifest:
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError, UnicodeError) as exc:
            raise ManifestError(f"could not load manifest {path}") from exc
        try:
            return _from_data(data)
        except ManifestError:
            raise
        except Exception as exc:  # defensive boundary for malformed external data
            raise ManifestError(f"invalid manifest {path}") from exc

    @staticmethod
    def save(path: Path, manifest: JobManifest) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            _data(manifest), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
            ) as handle:
                temporary = handle.name
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                with suppress(FileNotFoundError):
                    os.unlink(temporary)
