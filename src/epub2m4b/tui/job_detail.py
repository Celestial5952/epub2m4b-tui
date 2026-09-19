"""Job detail screen: real progress, cost estimate, and the paid-work boundary."""

from __future__ import annotations

from contextlib import suppress
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Input, ProgressBar, Static

from epub2m4b.app.jobs import JobSummary
from epub2m4b.app.service import ApplicationService
from epub2m4b.exceptions import Epub2M4BError
from epub2m4b.generation.estimate import NarrationEstimate

from .navigation import NavigationBar

_CONFIRM_WORD = "START"


class ConversionErrorScreen(ModalScreen[str | None]):
    """Prominent, unmistakable modal alert when conversion stops with an error."""

    def __init__(
        self,
        book_title: str,
        error_message: str,
        completed_chunks: int = 0,
        total_chunks: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.book_title = book_title
        self.error_message = error_message
        self.completed_chunks = completed_chunks
        self.total_chunks = total_chunks

    def compose(self) -> ComposeResult:
        is_credential_issue = (
            "OpenAI is not configured" in self.error_message
            or "API key" in self.error_message
        )
        with Container(id="error-dialog"):
            yield Static("⚠ Conversion Stopped: Error", id="error-heading")
            yield Static(f'Book: "{self.book_title}"', id="error-book")
            yield Static(f"What happened:\n{self.error_message}", id="error-detail")
            yield Static(
                f"Your progress is safe: {self.completed_chunks} of {self.total_chunks} "
                "audio piece(s) are saved on disk and will not need to be regenerated.",
                id="error-reassurance",
            )
            with Horizontal(id="error-actions"):
                if is_credential_issue:
                    yield Button("Go to Settings", id="error-settings", variant="primary")
                else:
                    yield Button("Try again", id="error-retry", variant="primary")
                yield Button("Dismiss", id="error-dismiss")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "error-settings":
            self.dismiss("settings")
        elif button_id == "error-retry":
            self.dismiss("retry")
        else:
            self.dismiss(None)

_STATUS_LABELS = {
    "ready": "Ready — no narration started",
    "running": "Narrating",
    "paused": "Paused",
    "cancelled": "Cancelled",
    "failed": "Needs attention",
    "complete": "Complete",
}


def _status_label(summary: JobSummary) -> str:
    value = str(getattr(summary.status, "value", summary.status))
    return _STATUS_LABELS.get(value, "Unknown")


def _format_hours_minutes(seconds: int) -> str:
    minutes = max(1, round(seconds / 60))
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"about {hours} hours {rest} minutes"
    if hours:
        return f"about {hours} hours"
    return f"about {rest} minutes"


def _format_cost(cost: Decimal) -> str:
    cents = cost.quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    return f"${cents}"


class ConfirmPreviewScreen(ModalScreen[bool]):
    """Modal confirmation showing cost estimate before synthesizing a preview sample."""

    def __init__(
        self,
        book_title: str,
        estimate: NarrationEstimate,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.book_title = book_title
        self.estimate = estimate

    def compose(self) -> ComposeResult:
        with Container(id="confirm-preview-dialog"):
            yield Static("🎧 Generate Narration Sample", id="confirm-preview-heading")
            yield Static(f'Book: "{self.book_title}"', id="confirm-preview-book")
            yield Static(
                f"Estimated cost: {_format_cost(self.estimate.estimated_cost_usd)} "
                f"for {self.estimate.character_count} characters "
                f"({_format_hours_minutes(self.estimate.estimated_seconds)} of audio).",
                id="confirm-preview-estimate",
            )
            yield Static(
                "This will synthesize a short sample of the opening chapter using your "
                "configured voice and narration settings. It uses your OpenAI API key.",
                id="confirm-preview-instruction",
            )
            with Horizontal(id="confirm-preview-actions"):
                yield Button("Generate sample", id="confirm-preview-start", variant="primary")
                yield Button("Cancel", id="confirm-preview-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-preview-start":
            self.dismiss(True)
        elif event.button.id == "confirm-preview-cancel":
            self.dismiss(False)


class ConfirmGenerationScreen(ModalScreen[bool]):
    """Unmistakable paid-work boundary: show the price, then require typing."""

    def __init__(
        self,
        book_title: str,
        estimate: NarrationEstimate,
        remaining_chunks: int,
        action_label: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.book_title = book_title
        self.estimate = estimate
        self.remaining_chunks = remaining_chunks
        self.action_label = action_label

    def compose(self) -> ComposeResult:
        with Container(id="confirm-dialog"):
            yield Static("This step spends money", id="confirm-heading")
            yield Static(
                f'"{self.book_title}" still needs {self.remaining_chunks} audio piece(s).',
                id="confirm-book",
            )
            yield Static(
                "Estimated cost: "
                f"{_format_cost(self.estimate.estimated_cost_usd)} "
                f"(estimate already includes a 15% safety margin)\n"
                f"Estimated listening length: "
                f"{_format_hours_minutes(self.estimate.estimated_seconds)}\n"
                "The app refuses to run if the estimate ever goes above your "
                "spending limit in Settings.",
                id="confirm-estimate",
            )
            yield Static(
                f'Type "{_CONFIRM_WORD}" and press the button to '
                f"{self.action_label}.",
                id="confirm-instruction",
            )
            yield Input(placeholder=f"Type {_CONFIRM_WORD} here", id="confirm-input")
            with Horizontal(id="confirm-actions"):
                yield Button(
                    self.action_label.capitalize(),
                    id="confirm-start",
                    variant="error",
                    disabled=True,
                )
                yield Button("Not now", id="confirm-cancel")

    def _ready(self) -> bool:
        typed = self.query_one("#confirm-input", Input).value.strip().upper()
        return typed == _CONFIRM_WORD

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "confirm-input":
            self.query_one("#confirm-start", Button).disabled = not self._ready()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "confirm-input" and self._ready():
            self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-start":
            self.dismiss(self._ready())
        elif event.button.id == "confirm-cancel":
            self.dismiss(False)


class JobDetailScreen(Screen[None]):
    """Watch one job, start paid narration only behind a typed confirmation."""

    def __init__(self, service: ApplicationService, summary: JobSummary, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.service = service
        self.summary = summary
        self._generation_running = False
        self._estimate_available = True
        self._output_path: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="job-detail"):
            yield NavigationBar("jobs")
            with Horizontal(id="detail-heading"):
                yield Button("← Back to jobs", id="back-jobs")
                yield Button("Refresh", id="refresh-detail")
            with VerticalScroll(id="detail-body"):
                yield Static("", id="detail-title")
                yield Static("", id="detail-info")
                yield Static("", id="detail-status")
                yield ProgressBar(
                    total=max(1, self.summary.total_chunks),
                    show_eta=False,
                    id="detail-progress",
                )
                with Container(id="detail-error-box"):
                    yield Static("⚠ Conversion stopped with an error", id="detail-error-title")
                    yield Static("", id="detail-error-message")
                    yield Static(
                        "Your completed audio pieces are saved safely. "
                        "You can resume narration once the issue is resolved.",
                        id="detail-error-advice",
                    )
                    with Horizontal(id="detail-error-actions"):
                        yield Button(
                            "Open Settings", id="detail-error-settings", variant="primary"
                        )
                yield Static("", id="detail-message")
                yield Static("", id="detail-estimate")
                with Container(id="detail-preview-box"):
                    yield Static("Narration Sample", classes="section-title")
                    yield Static(
                        "Hear how your chosen voice sounds reading the opening prose of this book.",
                        classes="detail-subtext",
                    )
                    with Horizontal(id="detail-preview-actions"):
                        yield Button(
                            "Generate 30s sample…", id="preview-sample", variant="primary"
                        )
                        yield Button(
                            "▶ Play sample", id="play-sample", variant="success", disabled=True
                        )
                        yield Button("■ Stop sample", id="stop-sample", disabled=True)
            with Horizontal(id="detail-actions"):
                yield Button("Start narrating…", id="start-narrating", variant="primary")
                yield Button("Pause", id="pause-job")
                yield Button("Cancel narration", id="cancel-job", variant="error")
                yield Button("Open audiobook", id="open-audiobook", variant="success")
        yield Footer()

    async def on_mount(self) -> None:
        self._render_view()
        await self._refresh_estimate()
        self.set_interval(1.0, self._poll_persisted_progress)

    async def _poll_persisted_progress(self) -> None:
        """Keep a reopened detail screen synchronized with app-owned generation."""

        if not self._generation_running:
            await self._refresh_summary()

    # ----- rendering -----------------------------------------------------

    def _render_view(self) -> None:
        summary = self.summary
        authors = ", ".join(summary.authors) if summary.authors else "Unknown author"
        self.query_one("#detail-title", Static).update(summary.title)
        info = f"Author: {authors}\nReference: {summary.job_id}"
        if summary.narration is not None:
            narration = summary.narration
            info += (
                f"\nNarration: {narration.provider}, model {narration.model}, "
                f"voice {narration.voice}, speed {narration.speed:g}"
            )
            if narration.instructions:
                info += f"\nNarration style: {narration.instructions}"
        if getattr(summary, "path", None):
            info += f"\nJob directory: {summary.path}"
        if getattr(summary, "updated_at", None):
            info += f"\nLast updated: {summary.updated_at}"
        self.query_one("#detail-info", Static).update(info)
        progress = self.query_one("#detail-progress", ProgressBar)
        progress.total = max(1, summary.total_chunks)
        progress.completed = summary.completed_chunks
        self._render_status()
        self._render_controls()
        status_value = str(getattr(self.summary.status, "value", self.summary.status))
        if status_value == "failed":
            self._show_error(
                "This job needs attention. Conversion previously stopped before completing.",
                push_modal=False,
            )
        elif status_value in {"ready", "paused", "complete", "cancelled"}:
            self._hide_error()

    def _show_error(self, message: str, *, push_modal: bool = True) -> None:
        with suppress(Exception):
            error_box = self.query_one("#detail-error-box", Container)
            error_box.styles.display = "block"
            self.query_one("#detail-error-message", Static).update(message)
            settings_btn = self.query_one("#detail-error-settings", Button)
            is_cred = "OpenAI is not configured" in message or "API key" in message
            settings_btn.display = is_cred
        self._message(f"Stopped: {message}")
        if push_modal:
            def dismissed(action: str | None) -> None:
                if action == "settings":
                    self.app.show_settings()  # type: ignore[attr-defined]
                elif action == "retry":
                    self.app.run_worker(self._start_flow())

            self.app.push_screen(
                ConversionErrorScreen(
                    book_title=self.summary.title,
                    error_message=message,
                    completed_chunks=self.summary.completed_chunks,
                    total_chunks=self.summary.total_chunks,
                ),
                dismissed,
            )

    def _hide_error(self) -> None:
        with suppress(Exception):
            error_box = self.query_one("#detail-error-box", Container)
            error_box.styles.display = "none"

    def _render_status(self) -> None:
        summary = self.summary
        percent = (
            round(summary.completed_chunks * 100 / summary.total_chunks)
            if summary.total_chunks
            else 0
        )
        label = "Narrating" if self._generation_running else _status_label(summary)
        self.query_one("#detail-status", Static).update(
            f"{label}: {summary.completed_chunks} of {summary.total_chunks} "
            f"audio pieces ({percent}%)"
        )

    def _render_controls(self) -> None:
        status_value = str(getattr(self.summary.status, "value", self.summary.status))
        start = self.query_one("#start-narrating", Button)
        pause = self.query_one("#pause-job", Button)
        cancel = self.query_one("#cancel-job", Button)
        open_button = self.query_one("#open-audiobook", Button)
        running = self._generation_running
        start.display = not running and status_value not in {"complete", "cancelled"}
        start.disabled = (
            running
            or not self._estimate_available
            or status_value in {"running", "complete", "cancelled"}
        )
        pause.display = running
        pause.disabled = not running
        cancel.display = running
        cancel.disabled = not running
        open_button.display = self._output_path is not None
        open_button.disabled = self._output_path is None
        if status_value == "ready":
            start.label = "Start narrating…"
        elif status_value == "paused":
            start.label = "Resume narrating…"
        elif status_value == "failed":
            start.label = "Try again…"
        elif status_value == "running":
            start.label = "Continue narrating…"

        preview_path = None
        with suppress(Exception):
            preview_path = self.service.get_job_preview(self.summary.job_id)
        has_preview = preview_path is not None
        preview_btn = self.query_one("#preview-sample", Button)
        play_sample_btn = self.query_one("#play-sample", Button)
        stop_sample_btn = self.query_one("#stop-sample", Button)
        preview_btn.disabled = running
        play_sample_btn.disabled = running or not has_preview
        stop_sample_btn.disabled = running or not has_preview

    def _message(self, text: str) -> None:
        self.query_one("#detail-message", Static).update(text)

    async def _preview_flow(self) -> None:
        if self._generation_running:
            return
        try:
            estimate = await self.service.estimate_job_preview(self.summary.job_id)
        except Exception as exc:
            error_msg = (
                str(exc)
                if isinstance(exc, Epub2M4BError)
                else "The preview estimate could not be prepared."
            )
            self._show_error(error_msg, push_modal=True)
            return

        def confirmed(result: bool) -> None:
            if result:
                self.app.run_worker(
                    self._generate_preview(estimate.estimated_cost_usd),
                    group=f"preview-{self.summary.job_id}",
                    exclusive=True,
                )

        self.app.push_screen(
            ConfirmPreviewScreen(self.summary.title, estimate),
            confirmed,
        )

    async def _generate_preview(self, authorized: Decimal) -> None:
        self._message("Generating narration sample…")
        try:
            await self.service.generate_job_preview(self.summary.job_id, authorized)
        except Exception as exc:
            error_msg = (
                str(exc)
                if isinstance(exc, Epub2M4BError)
                else "Could not generate narration preview."
            )
            self._show_error(error_msg, push_modal=True)
            return
        if self._is_current_screen():
            self._render_controls()
            self._message("Sample ready. Click '▶ Play sample' to listen.")

    def _play_sample(self) -> None:
        preview = self.service.get_job_preview(self.summary.job_id)
        if preview is None:
            self._message("No sample preview has been generated yet.")
            return
        try:
            self.service.play_audio_file(preview)
            self._message("Playing book preview sample…")
        except Exception as exc:
            self._message(f"Could not play sample: {exc}")

    def _stop_sample(self) -> None:
        try:
            self.service.stop_voice_preview()
            self._message("Playback stopped.")
        except Exception:
            pass

    def _is_current_screen(self) -> bool:
        """Return whether this screen still owns visible widgets."""

        try:
            return self.is_mounted and self.app.screen is self
        except Exception:
            return False

    # ----- data ----------------------------------------------------------

    async def _refresh_summary(self) -> None:
        try:
            jobs = await self.service.list_jobs()
        except Exception:
            return
        for job in jobs:
            if job.job_id == self.summary.job_id:
                self.summary = job
                break
        self._render_view()

    async def _refresh_estimate(self) -> None:
        status_value = str(getattr(self.summary.status, "value", self.summary.status))
        estimate_area = self.query_one("#detail-estimate", Static)
        if status_value not in {"ready", "paused", "failed"}:
            estimate_area.update("")
            return
        try:
            estimate = await self.service.estimate_job(self.summary.job_id)
        except Epub2M4BError as exc:
            estimate_area.update("")
            self._estimate_available = False
            self._render_controls()
            self._message(str(exc))
            return
        except Exception:
            estimate_area.update("")
            self._estimate_available = False
            self._render_controls()
            self._message("The cost estimate could not be loaded. Try Refresh.")
            return
        self._estimate_available = True
        self._render_controls()
        remaining = self.summary.total_chunks - self.summary.completed_chunks
        estimate_area.update(
            f"Remaining estimate: {_format_cost(estimate.estimated_cost_usd)} and "
            f"{_format_hours_minutes(estimate.estimated_seconds)} of listening, "
            f"for {remaining} audio piece(s).\n"
            f"Scope: {estimate.word_count:,} words · "
            f"{estimate.character_count:,} characters · "
            f"~{estimate.text_input_tokens:,} input tokens."
        )

    # ----- generation lifecycle ------------------------------------------

    async def _start_flow(self) -> None:
        if self._generation_running:
            return
        try:
            estimate = await self.service.estimate_job(self.summary.job_id)
        except Exception as exc:
            error_msg = (
                str(exc)
                if isinstance(exc, Epub2M4BError)
                else "The estimate could not be prepared."
            )
            self._show_error(error_msg, push_modal=True)
            return
        remaining = self.summary.total_chunks - self.summary.completed_chunks
        action = "start narration"
        status_value = str(getattr(self.summary.status, "value", self.summary.status))
        if status_value == "paused":
            action = "resume narration"
        elif status_value in {"failed", "running"}:
            action = "continue narration"

        def confirmed(result: bool) -> None:
            if result:
                # The App owns long-running narration. Screen-owned workers are
                # cancelled by Textual when the user navigates to another tab.
                self.app.run_worker(
                    self._generate(estimate.estimated_cost_usd),
                    group=f"narration-{self.summary.job_id}",
                    exclusive=True,
                )

        self.app.push_screen(
            ConfirmGenerationScreen(self.summary.title, estimate, remaining, action),
            confirmed,
        )

    async def _generate(self, authorized: Decimal) -> None:
        self._generation_running = True
        self._hide_error()
        self._render_controls()
        self._message("Narration is starting. Keep this screen open to watch progress.")
        error_occurred: str | None = None
        try:
            async for event in self.service.generate(self.summary.job_id, authorized):
                if self._is_current_screen():
                    self._apply_event(event)
        except Epub2M4BError as exc:
            error_occurred = str(exc)
        except Exception as exc:
            error_occurred = (
                f"Narration stopped unexpectedly ({type(exc).__name__}: {exc}). "
                "Your finished pieces are kept."
            )
        finally:
            self._generation_running = False
            if self._is_current_screen():
                await self._refresh_summary()
                self._render_controls()
                self._render_status()
                status_value = str(getattr(self.summary.status, "value", self.summary.status))
                if error_occurred:
                    self._show_error(error_occurred, push_modal=True)
                elif status_value == "paused":
                    self._message("Paused. Finished audio pieces are kept for next time.")
                elif status_value == "cancelled":
                    self._message(
                        "Cancelled. Finished pieces are kept; set this book up again "
                        "from Library to reuse them."
                    )

    def _apply_event(self, event: Any) -> None:
        progress = self.query_one("#detail-progress", ProgressBar)
        if event.total_chunks:
            progress.total = event.total_chunks
        progress.completed = event.completed_chunks
        self._message(str(event.message))
        if event.output_path:
            self._output_path = str(event.output_path)
            open_button = self.query_one("#open-audiobook", Button)
            open_button.disabled = False
            open_button.display = True
            self._message(f"Finished. Audiobook saved to {self._output_path}")

    async def _pause(self) -> None:
        if not self._generation_running:
            return
        try:
            await self.service.pause(self.summary.job_id)
        except Epub2M4BError as exc:
            self._message(str(exc))
            return
        self._message("Pausing after the current audio piece…")

    async def _cancel(self) -> None:
        if not self._generation_running:
            return
        try:
            await self.service.cancel(self.summary.job_id)
        except Epub2M4BError as exc:
            self._message(str(exc))
            return
        self._message("Cancelling after the current audio piece…")

    def _open_audiobook(self) -> None:
        if self._output_path is None:
            return
        try:
            self.service.open_audiobook(Path(self._output_path))
        except Epub2M4BError as exc:
            self._message(str(exc))
            return
        self._message("Opened the audiobook with your default player.")

    # ----- events --------------------------------------------------------

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "back-jobs":
            self.app.show_jobs()  # type: ignore[attr-defined]
        elif button_id == "refresh-detail":
            self._message("")
            await self._refresh_summary()
            await self._refresh_estimate()
        elif button_id == "start-narrating":
            await self._start_flow()
        elif button_id == "pause-job":
            await self._pause()
        elif button_id == "cancel-job":
            await self._cancel()
        elif button_id == "open-audiobook":
            self._open_audiobook()
        elif button_id == "preview-sample":
            await self._preview_flow()
        elif button_id == "play-sample":
            self._play_sample()
        elif button_id == "stop-sample":
            self._stop_sample()
        elif button_id == "detail-error-settings":
            self.app.show_settings()  # type: ignore[attr-defined]
        elif button_id == "nav-library":
            self.app.show_library()  # type: ignore[attr-defined]
        elif button_id == "nav-jobs":
            self.app.show_jobs()  # type: ignore[attr-defined]
        elif button_id == "nav-voices":
            self.app.show_voices()  # type: ignore[attr-defined]
        elif button_id == "nav-settings":
            self.app.show_settings()  # type: ignore[attr-defined]
        elif button_id == "nav-logs":
            self.app.show_logs()  # type: ignore[attr-defined]

    def on_unmount(self) -> None:
        with suppress(Exception):
            self.service.stop_voice_preview()


__all__ = [
    "ConfirmGenerationScreen",
    "ConfirmPreviewScreen",
    "ConversionErrorScreen",
    "JobDetailScreen",
]
