"""Job overview with clickable entries leading to detail, estimate, and actions."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from epub2m4b.app.jobs import JobSummary
from epub2m4b.app.service import ApplicationService

from .delete_job import DeleteJobScreen
from .navigation import NavigationBar

_STATUS_LABELS = {
    "ready": "Ready — no narration started",
    "running": "Narrating",
    "paused": "Paused",
    "cancelled": "Cancelled",
    "failed": "Needs attention",
    "complete": "Complete",
}


def _status_label(job: JobSummary) -> str:
    value = str(getattr(job.status, "value", job.status))
    return _STATUS_LABELS.get(value, "Unknown")


def _summary_text(job: JobSummary) -> str:
    if job.error:
        return f"{job.title}\n  {job.error}"
    total = int(job.total_chunks)
    complete = int(job.completed_chunks)
    percent = round(complete * 100 / total) if total else 0
    voice_info = f" · Voice: {job.narration.voice}" if job.narration is not None else ""
    return (
        f"{job.title}\n"
        f"  {_status_label(job)}{voice_info}\n"
        f"  Progress: {complete} of {total} audio pieces ({percent}%)"
    )


class JobCard(Container):
    """One clickable persisted job."""

    def __init__(self, job: JobSummary) -> None:
        super().__init__(classes="job-card")
        self.job = job
        self.border_title = job.job_id

    def compose(self) -> ComposeResult:
        yield Static(_summary_text(self.job), classes="job-summary")
        with Horizontal(classes="job-card-actions"):
            yield Button(
                "View details & estimate",
                id=f"view-{self.job.job_id}",
                variant="primary",
            )
            yield Button(
                "Delete old job",
                id=f"delete-{self.job.job_id}",
                variant="error",
            )


class JobsScreen(Screen[None]):
    """Show persisted jobs and open any of them for detail and actions."""

    def __init__(self, service: ApplicationService, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.service = service

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="jobs"):
            yield NavigationBar("jobs")
            with Horizontal(id="jobs-heading"):
                yield Static("Audiobook jobs", id="jobs-title")
                yield Button("Refresh", id="refresh-jobs")
            yield Static(
                "A job marked Ready has not contacted a narration provider "
                "and has not used credits. Choose a book to see its details, "
                "cost estimate, and controls.",
                id="jobs-help",
            )
            yield Static("Loading jobs…", id="jobs-status")
            with VerticalScroll(id="jobs-list"):
                pass
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_jobs()

    async def refresh_jobs(self) -> None:
        refresh = self.query_one("#refresh-jobs", Button)
        refresh.disabled = True
        try:
            jobs = await self.service.list_jobs()
        except Exception:
            self.query_one("#jobs-status", Static).update(
                "Jobs could not be loaded. Try Refresh."
            )
            await self.query_one("#jobs-list", VerticalScroll).remove_children()
            return
        finally:
            refresh.disabled = False
        job_list = self.query_one("#jobs-list", VerticalScroll)
        await job_list.remove_children()
        if not jobs:
            self.query_one("#jobs-status", Static).update("No audiobook jobs yet.")
            return
        self.query_one("#jobs-status", Static).update(f"{len(jobs)} job(s)")
        for job in jobs:
            await job_list.mount(JobCard(job))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "refresh-jobs":
            await self.refresh_jobs()
        elif button_id.startswith("view-"):
            await self._open_detail(button_id.removeprefix("view-"))
        elif button_id.startswith("delete-"):
            self._confirm_delete(button_id.removeprefix("delete-"))
        elif button_id == "nav-library":
            self.app.show_library()  # type: ignore[attr-defined]
        elif button_id == "nav-voices":
            self.app.show_voices()  # type: ignore[attr-defined]
        elif button_id == "nav-settings":
            self.app.show_settings()  # type: ignore[attr-defined]
        elif button_id == "nav-logs":
            self.app.show_logs()  # type: ignore[attr-defined]

    async def _open_detail(self, job_id: str) -> None:
        try:
            jobs = await self.service.list_jobs()
        except Exception:
            self.query_one("#jobs-status", Static).update(
                "Jobs could not be loaded. Try Refresh."
            )
            return
        for job in jobs:
            if job.job_id == job_id:
                self.app.show_job_detail(job)  # type: ignore[attr-defined]
                return

    def _confirm_delete(self, job_id: str) -> None:
        cards = self.query(JobCard)
        title = next(
            (card.job.title for card in cards if card.job.job_id == job_id),
            "this audiobook",
        )

        def confirmed(should_delete: bool) -> None:
            if should_delete:
                self.run_worker(self._delete_job(job_id), exclusive=True)

        self.app.push_screen(DeleteJobScreen(title), confirmed)

    async def _delete_job(self, job_id: str) -> None:
        try:
            await self.service.delete_job(job_id)
        except Exception as exc:
            detail = str(exc).strip() or "unknown local error"
            self.query_one("#jobs-status", Static).update(f"Could not delete job: {detail}")
            return
        await self.refresh_jobs()
        self.query_one("#jobs-status", Static).update("Old job deleted.")


__all__ = ["JobCard", "JobsScreen"]
