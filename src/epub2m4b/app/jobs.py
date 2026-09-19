"""Read-only discovery of persisted narration jobs."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from epub2m4b.generation.manifest import ManifestRepository
from epub2m4b.models import ChunkStatus, JobManifest, JobStatus, NarrationSettings

_JOB_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class JobSummary:
    job_id: str
    title: str
    authors: tuple[str, ...]
    status: JobStatus | str
    completed_chunks: int
    total_chunks: int
    updated_at: str | None
    path: Path
    error: str | None = None
    narration: NarrationSettings | None = None


def _valid_job_id(job_id: str) -> bool:
    return bool(_JOB_ID.fullmatch(job_id))


def _sort_time(value: str | None) -> float:
    if not value:
        return float("-inf")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        return stamp.timestamp()
    except (TypeError, ValueError, OverflowError):
        return float("-inf")


class JobStore:
    """Discover job manifests without changing any existing job state."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def ensure(self) -> JobStore:
        self.root.mkdir(parents=True, exist_ok=True)
        return self

    def manifest_path(self, job_id: str) -> Path:
        if not isinstance(job_id, str) or not _valid_job_id(job_id):
            raise ValueError("unsafe job ID")
        return self.root / job_id / "manifest.json"

    def delete(self, job_id: str) -> None:
        """Delete exactly one safe direct-child job directory."""

        directory = self.manifest_path(job_id).parent
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("job does not exist")
        if directory.parent.resolve(strict=True) != self.root.resolve(strict=True):
            raise ValueError("unsafe job directory")
        shutil.rmtree(directory)

    def _error_summary(self, job_id: str, path: Path) -> JobSummary:
        return JobSummary(
            job_id=job_id,
            title="Unavailable job",
            authors=(),
            status=JobStatus.FAILED,
            completed_chunks=0,
            total_chunks=0,
            updated_at=None,
            path=path.parent,
            error="manifest unavailable",
        )

    def _discover(self) -> tuple[tuple[Path, JobManifest | None, str | None], ...]:
        """Return ``(directory, manifest, error)`` triples for safe direct children.

        ``manifest`` is ``None`` when the manifest is missing or corrupt; callers
        decide whether to surface an error summary or skip the entry.
        """

        if not self.root.is_dir() or self.root.is_symlink():
            return ()
        discovered: list[tuple[Path, JobManifest | None, str | None]] = []
        for entry in self.root.iterdir():
            if not entry.is_dir() or entry.is_symlink() or not _valid_job_id(entry.name):
                continue
            path = entry / "manifest.json"
            try:
                manifest = ManifestRepository.load(path)
                if manifest.job_id != entry.name or not _valid_job_id(manifest.job_id):
                    raise ValueError("manifest job ID does not match its directory")
            except Exception:
                discovered.append((entry, None, "manifest unavailable"))
                continue
            discovered.append((entry, manifest, None))
        return tuple(discovered)

    def manifests(self) -> tuple[JobManifest, ...]:
        """Return every readable manifest without changing any job state."""

        return tuple(
            manifest
            for _, manifest, _ in self._discover()
            if manifest is not None
        )

    def list(self) -> tuple[JobSummary, ...]:
        summaries: list[JobSummary] = []
        for entry, manifest, _error in self._discover():
            if manifest is None:
                summaries.append(self._error_summary(entry.name, entry / "manifest.json"))
                continue
            completed = sum(1 for chunk in manifest.chunks if chunk.status is ChunkStatus.COMPLETE)
            summaries.append(
                JobSummary(
                    job_id=manifest.job_id,
                    title=manifest.book.title,
                    authors=manifest.book.authors,
                    status=manifest.status,
                    completed_chunks=completed,
                    total_chunks=len(manifest.chunks),
                    updated_at=manifest.updated_at,
                    path=entry,
                    narration=manifest.narration,
                )
            )
        summaries.sort(key=lambda item: (-_sort_time(item.updated_at), item.job_id))
        return tuple(summaries)
