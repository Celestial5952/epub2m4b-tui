"""Read-only audit trail of every provider request, outcome, and money boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from epub2m4b.app.audit import AuditEntry
from epub2m4b.app.service import ApplicationService

from .navigation import NavigationBar

_KIND_WIDTH = 10


def _format_timestamp(timestamp: str) -> str:
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp[:19]
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _format_characters(characters: int | None) -> str:
    if characters is None:
        return ""
    return f"{characters:,} chars"


def _format_job(job_id: str | None) -> str:
    if not job_id:
        return ""
    return f"job …{job_id[-8:]}"


def format_log_line(entry: AuditEntry) -> str:
    """One fixed-order, human-readable line for the Logs screen."""

    parts = [
        _format_timestamp(entry.timestamp),
        entry.kind.upper().ljust(_KIND_WIDTH),
    ]
    context = " · ".join(
        piece
        for piece in (
            entry.provider,
            entry.model,
            entry.voice,
            _format_job(entry.job_id),
            _format_characters(entry.characters),
        )
        if piece
    )
    if context:
        parts.append(context)
    parts.append(entry.message)
    return "  ".join(parts)


class LogsScreen(Screen[None]):
    """Show the newest audit entries; refresh on demand."""

    def __init__(self, service: ApplicationService, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.service = service

    def compose(self) -> ComposeResult:
        try:
            location = self.service.audit_log_location()
            hint = (
                "Every narration provider request, its outcome, and each "
                "money decision is recorded here. The full history is kept "
                f"on this computer at {location}."
            )
        except Exception:
            hint = "Every narration provider request and outcome is recorded here."
        yield Header(show_clock=False)
        with Container(id="logs-screen"):
            yield NavigationBar("logs")
            with Horizontal(id="logs-heading"):
                yield Static("Activity log", id="logs-title")
                yield Button("Refresh", id="refresh-logs")
            yield Static(hint, id="logs-help")
            yield Static("Loading activity…", id="logs-status")
            with VerticalScroll(id="logs-list"):
                pass
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_logs()

    async def refresh_logs(self) -> None:
        refresh = self.query_one("#refresh-logs", Button)
        refresh.disabled = True
        try:
            entries = await self.service.audit_entries(300)
        except Exception:
            self.query_one("#logs-status", Static).update(
                "The activity log could not be loaded. Try Refresh."
            )
            await self.query_one("#logs-list", VerticalScroll).remove_children()
            return
        finally:
            refresh.disabled = False
        log_list = self.query_one("#logs-list", VerticalScroll)
        await log_list.remove_children()
        if not entries:
            self.query_one("#logs-status", Static).update(
                "Nothing has been logged yet. Estimates, narration requests, "
                "and outcomes will appear here."
            )
            return
        self.query_one("#logs-status", Static).update(
            f"{len(entries)} most recent entr{'y' if len(entries) == 1 else 'ies'}"
        )
        for entry in entries:
            await log_list.mount(Static(format_log_line(entry), classes="log-line"))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "refresh-logs":
            await self.refresh_logs()
        elif button_id == "nav-library":
            self.app.show_library()  # type: ignore[attr-defined]
        elif button_id == "nav-jobs":
            self.app.show_jobs()  # type: ignore[attr-defined]
        elif button_id == "nav-voices":
            self.app.show_voices()  # type: ignore[attr-defined]
        elif button_id == "nav-settings":
            self.app.show_settings()  # type: ignore[attr-defined]


__all__ = ["LogsScreen", "format_log_line"]
