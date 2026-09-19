"""Export-and-reset support for a deliberate fresh onboarding."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

from epub2m4b.app.audit import AuditLog, sanitize
from epub2m4b.config import AppConfig
from epub2m4b.config_store import ConfigRepository
from epub2m4b.credentials import CredentialService
from epub2m4b.exceptions import GenerationError


def _settings(config: AppConfig) -> dict[str, object]:
    """Convert the non-secret configuration to JSON-safe values."""

    values = asdict(config)
    for name in ("cache_directory", "book_directory", "output_directory", "work_directory"):
        value = values[name]
        if value is not None:
            values[name] = str(value)
    return values


def _write_export(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=f".{path.name}.", suffix=".tmp",
            dir=path.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _remove_tree(path: Path) -> None:
    """Remove an explicit application-owned tree, rejecting broad targets."""

    resolved = path.resolve(strict=False)
    if resolved in {Path("/"), Path.home()}:
        raise GenerationError("reset refused an unsafe application-state path")
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def force_reonboard(
    *,
    config_path: Path,
    audit: AuditLog,
    jobs_root: Path,
    cache_root: Path,
    credentials: CredentialService,
    export_path: Path,
    exported_at: datetime,
) -> Path:
    """Export non-secret settings/audit data, then clear owned app state.

    EPUB source folders and completed audiobook output directories are never
    deleted. The export deliberately contains credential status neither values
    nor headers; saved provider credentials are removed after a durable export.
    """

    config = ConfigRepository.load(config_path)
    entries = [
        replace(entry, message=sanitize(entry.message)).to_dict()
        for entry in audit.entries(limit=1_000_000)
    ]
    _write_export(
        export_path,
        {
            "schema_version": 1,
            "exported_at": exported_at.isoformat(),
            "settings": _settings(config),
            "audit_entries": entries,
            "credentials_exported": False,
        },
    )
    try:
        credentials.delete("openai")
        credentials.delete("elevenlabs")
    except Exception as exc:
        raise GenerationError("saved credentials could not be removed") from exc

    if any(
        export_path.resolve(strict=False).is_relative_to(path.resolve(strict=False))
        for path in (jobs_root, cache_root)
    ):
        raise GenerationError("reset export must be outside application-state directories")
    for path in (jobs_root, cache_root):
        _remove_tree(path)
    for path in (audit.path, audit.backup_path, config_path):
        path.unlink(missing_ok=True)
    return export_path


__all__ = ["force_reonboard"]
