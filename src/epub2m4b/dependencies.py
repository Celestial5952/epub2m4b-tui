"""Offline discovery of local multimedia dependencies."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    """Availability of one executable dependency."""

    name: str
    required: bool
    available: bool
    path: Path | None


@dataclass(frozen=True, slots=True)
class DependencyReport:
    """Immutable dependency results in stable executable order."""

    entries: tuple[DependencyStatus, ...]

    @property
    def required_available(self) -> bool:
        return all(entry.available for entry in self.entries if entry.required)

    @property
    def preview_available(self) -> bool:
        return any(entry.available for entry in self.entries if not entry.required)


def check_dependencies(
    resolver: Callable[[str], object | None] = shutil.which,
) -> DependencyReport:
    """Resolve required FFmpeg tools and the optional preview player.

    Resolution is deliberately the only operation performed here.  Resolver
    failures are isolated per executable and never leak exception details.
    """

    entries: list[DependencyStatus] = []
    for name, required in (("ffmpeg", True), ("ffprobe", True), ("ffplay", False)):
        try:
            candidate = resolver(name)
        except Exception:
            candidate = None
        path = Path(candidate) if isinstance(candidate, str) and candidate.strip() else None
        entries.append(DependencyStatus(name, required, path is not None, path))
    return DependencyReport(tuple(entries))
