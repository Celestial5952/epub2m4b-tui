from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from epub2m4b.app.audit import AuditEntry
from epub2m4b.app.events import ProgressEvent
from epub2m4b.app.jobs import JobSummary
from epub2m4b.app.library import LibraryScan
from epub2m4b.app.onboarding import OnboardingState
from epub2m4b.generation.estimate import NarrationEstimate
from epub2m4b.models import Book, JobManifest


class ApplicationService(Protocol):
    """The only backend surface available to CLI and TUI layers."""

    def onboarding_state(self) -> OnboardingState: ...

    def complete_onboarding(
        self,
        voice_id: str,
        cache_directory: Path | None = None,
        book_directory: Path | None = None,
        *,
        output_directory: Path | None = None,
        provider: str | None = None,
        model: str | None = None,
        speed: float | None = None,
        instructions: str | None = None,
        maximum_estimated_cost_usd: float | None = None,
    ) -> None: ...

    def skip_onboarding(self) -> None: ...

    def set_openai_credential(self, secret: str) -> None: ...

    def remove_openai_credential(self) -> None: ...

    def force_reonboard(self) -> Path: ...

    async def test_openai_connection(self, model: str) -> str: ...

    def play_voice_preview(self, voice_id: str) -> None: ...

    def stop_voice_preview(self) -> None: ...

    def shutdown(self) -> None: ...

    async def inspect_book(self, source: Path) -> Book: ...

    async def scan_book_folder(self) -> LibraryScan: ...

    async def create_job(self, source: Path) -> JobManifest: ...

    async def list_jobs(self) -> tuple[JobSummary, ...]: ...

    async def delete_job(self, job_id: str) -> None: ...

    async def estimate_job(self, job_id: str) -> NarrationEstimate: ...

    async def estimate_job_preview(self, job_id: str) -> NarrationEstimate: ...

    async def generate_job_preview(
        self, job_id: str, authorized_max_cost_usd: Decimal
    ) -> Path: ...

    def get_job_preview(self, job_id: str) -> Path | None: ...

    def play_audio_file(self, path: Path) -> None: ...

    async def generate(
        self, job_id: str, authorized_max_cost_usd: Decimal
    ) -> AsyncIterator[ProgressEvent]: ...

    async def pause(self, job_id: str) -> None: ...

    async def resume(
        self, job_id: str, authorized_max_cost_usd: Decimal
    ) -> AsyncIterator[ProgressEvent]: ...

    async def cancel(self, job_id: str) -> None: ...

    def open_audiobook(self, path: Path) -> None: ...

    async def audit_entries(self, limit: int = 200) -> tuple[AuditEntry, ...]: ...

    def audit_log_location(self) -> Path: ...
