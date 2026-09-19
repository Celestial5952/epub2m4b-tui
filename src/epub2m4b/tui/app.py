"""Textual application shell."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import Static

from epub2m4b.app.jobs import JobSummary
from epub2m4b.app.service import ApplicationService

from .home import HomeScreen
from .job_detail import JobDetailScreen
from .jobs import JobsScreen
from .logs import LogsScreen
from .onboarding import OnboardingScreen
from .settings import SettingsScreen
from .voices import VoicesScreen


class EPUB2M4BApp(App[None]):
    """Application shell that routes first launch through onboarding."""

    TITLE = "EPUB2M4B Audiobook Studio"

    CSS = """
    #onboarding { padding: 2 4; height: 1fr; }
    .step { height: 1fr; padding: 1 0; }
    .voice-row { height: 3; }
    .directory-row { height: 3; width: 100%; }
    .directory-row Input { width: 1fr; }
    .directory-row Button { width: 14; }
    #navigation { dock: bottom; height: 3; align: right middle; }
    #navigation Button { margin-left: 1; }
    #message { color: $error; height: 2; }
    #home { padding: 1 4; height: 1fr; }
    #home-title { width: 1fr; text-style: bold; margin-bottom: 1; }
    #app-navigation { height: 3; width: 100%; margin-bottom: 1; }
    #app-navigation Button { width: 14; margin-right: 1; }
    #app-navigation Button:disabled {
        background: $primary;
        color: $text;
        opacity: 100%;
        text-style: bold;
    }
    .section-title { text-style: bold; color: $accent; margin-top: 1; }
    #library-row { width: 100%; height: 3; }
    #library-select { width: 1fr; }
    #refresh-library { width: 16; }
    #source-row { width: 100%; height: 3; }
    #source-path { width: 1fr; }
    #inspect { width: 16; }
    #book-details { height: 1fr; border: round $panel; padding: 1; }
    #prepare { dock: bottom; height: 3; width: 100%; }
    #voices-screen { padding: 1 4; height: 1fr; }
    #voices-heading { height: 3; width: 100%; }
    #voices-title { width: 1fr; text-style: bold; }
    #stop-all { width: 18; }
    #voices-help { margin-bottom: 1; color: $text-muted; }
    #voices-status { height: 2; color: $accent; }
    #voices-list { height: 1fr; }
    .voice-card { border: round $panel; padding: 1; margin-bottom: 1; height: auto; }
    .voice-card:hover { border: round $accent; }
    .voice-card.default-voice { border: round $accent; background: $surface; }
    .voice-card-header { height: auto; width: 100%; margin-bottom: 1; }
    .voice-card-title { text-style: bold; }
    .voice-card-info { color: $text-muted; }
    .voice-card-actions { height: 3; }
    .voice-card-actions Button { margin-right: 1; }
    #settings-screen { height: 1fr; }
    #settings-nav { height: 4; padding: 1 4 0 4; }
    #settings { padding: 0 4; height: 1fr; }
    #settings-inner { height: auto; }
    #settings-title { text-style: bold; margin-bottom: 1; }
    #settings-message { width: 1fr; color: $accent; }
    #settings-instructions { height: 8; }
    #settings-remove-credential { width: 28; margin-top: 1; }
    #settings-force-reonboard { width: 28; margin-top: 1; }
    #settings-footer { dock: bottom; height: 3; padding: 0 4; }
    #settings-footer Button { width: 24; }
    #logs-screen { padding: 1 4; height: 1fr; }
    #logs-heading { height: 3; width: 100%; }
    #logs-title { width: 1fr; text-style: bold; }
    #refresh-logs { width: 16; }
    #logs-help { margin-bottom: 1; color: $text-muted; }
    #logs-status { height: 2; }
    #logs-list { height: 1fr; }
    .log-line { padding: 0 1; }
    .log-line:hover { background: $surface; }
    #jobs { padding: 1 4; height: 1fr; }
    #jobs-heading { height: 3; width: 100%; }
    #jobs-title { width: 1fr; text-style: bold; }
    #refresh-jobs { width: 16; }
    #jobs-help { margin-bottom: 1; color: $text-muted; }
    #jobs-status { height: 2; }
    #jobs-list { height: 1fr; }
    .job-card { border: round $panel; padding: 1; margin-bottom: 1; height: auto; }
    .job-card:hover { border: round $accent; }
    .job-summary { color: $text; margin-bottom: 1; }
    .job-card Button { width: 28; }
    .job-card-actions { height: 3; }
    .job-card-actions Button { margin-right: 1; }
    #job-detail { padding: 1 2; height: 1fr; }
    #detail-heading { height: 3; margin-bottom: 1; }
    #detail-heading Button { margin-right: 1; }
    #detail-body { height: 1fr; }
    #detail-title { text-style: bold; }
    #detail-info { color: $text-muted; }
    #detail-status { margin-top: 1; }
    #detail-progress { width: 100%; margin-top: 1; }
    #detail-message { height: auto; min-height: 1; color: $accent; margin-top: 1; }
    #detail-error-box {
        border: heavy $error; background: $panel; padding: 1 2; margin-top: 1;
        display: none; height: auto;
    }
    #detail-error-title { text-style: bold; color: $error; }
    #detail-error-message { color: $text; margin-top: 1; }
    #detail-error-advice { color: $text-muted; margin-top: 1; }
    #detail-error-actions { height: 3; margin-top: 1; }
    #detail-error-actions Button { width: 18; }
    #detail-estimate { margin-top: 1; }
    #detail-preview-box {
        height: auto; margin-top: 1; border: round $panel; padding: 1;
        background: $surface;
    }
    #detail-preview-box:hover { border: round $accent; }
    #detail-preview-actions { height: 3; margin-top: 1; }
    #detail-preview-actions Button { margin-right: 1; }
    .detail-subtext { color: $text-muted; }
    #detail-actions { dock: bottom; height: 3; margin-top: 1; }
    #detail-actions Button { margin-right: 1; }
    ConfirmPreviewScreen { align: center middle; }
    #confirm-preview-dialog {
        width: 70%; height: auto; border: round $accent; padding: 1 2;
        background: $panel;
    }
    #confirm-preview-heading { text-style: bold; color: $accent; }
    #confirm-preview-book { margin-top: 1; }
    #confirm-preview-estimate { margin-top: 1; }
    #confirm-preview-instruction { margin-top: 1; color: $text-muted; }
    #confirm-preview-actions { height: 3; margin-top: 1; align: right middle; }
    #confirm-preview-actions Button { margin-left: 1; }
    ConfirmGenerationScreen { align: center middle; }
    #confirm-dialog {
        width: 70%; height: auto; border: round $error; padding: 1 2;
        background: $panel;
    }
    #confirm-heading { text-style: bold; color: $error; }
    #confirm-book { margin-top: 1; }
    #confirm-estimate { margin-top: 1; }
    #confirm-instruction { margin-top: 1; color: $accent; }
    #confirm-input { margin-top: 1; }
    #confirm-actions { height: 3; margin-top: 1; align: right middle; }
    #confirm-actions Button { margin-left: 1; }
    ConversionErrorScreen { align: center middle; }
    #error-dialog {
        width: 75%; height: auto; border: heavy $error; padding: 1 2;
        background: $panel;
    }
    #error-heading { text-style: bold; color: $error; }
    #error-book { margin-top: 1; text-style: bold; }
    #error-detail { margin-top: 1; color: $error; }
    #error-reassurance { margin-top: 1; color: $text-muted; }
    #error-actions { height: 3; margin-top: 1; align: right middle; }
    #error-actions Button { margin-left: 1; }
    DirectoryPickerScreen { align: center middle; }
    #directory-picker { width: 80%; height: 80%; border: round $accent; padding: 1; }
    #directory-tree { height: 1fr; }
    #directory-picker-actions { height: 3; align: right middle; }
    ForceReonboardScreen { align: center middle; }
    #force-reonboard-dialog {
        width: 75%; height: auto; border: heavy $error; padding: 1 2;
        background: $panel;
    }
    #force-reonboard-heading { text-style: bold; color: $error; }
    #force-reonboard-instruction { margin-top: 1; color: $accent; }
    #force-reonboard-input { margin-top: 1; }
    #force-reonboard-actions { height: 3; margin-top: 1; align: right middle; }
    #force-reonboard-actions Button { margin-left: 1; }
    DeleteJobScreen { align: center middle; }
    #delete-job-dialog {
        width: 70%; height: auto; border: heavy $error; padding: 1 2;
        background: $panel;
    }
    #delete-job-heading { text-style: bold; color: $error; }
    #delete-job-actions { height: 3; margin-top: 1; align: right middle; }
    #delete-job-actions Button { margin-left: 1; }
    """

    BINDINGS = [("ctrl+q", "quit", "Quit")]

    def __init__(self, service: ApplicationService, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.service = service
        self._shutdown_called = False
        self._initial_state: Any = None

    def compose(self) -> ComposeResult:
        try:
            self._initial_state = self.service.onboarding_state()
        except Exception:
            yield Static("The application could not load onboarding state.")
            return
        yield Static("Loading EPUB2M4B…")

    def on_mount(self) -> None:
        if self._initial_state is None:
            return
        if self._initial_state.completed:
            self.push_screen(HomeScreen(self.service))
        else:
            self.push_screen(OnboardingScreen(self.service, self._initial_state))

    def show_home(self) -> None:
        self.switch_screen(HomeScreen(self.service))

    def show_library(self) -> None:
        self.switch_screen(HomeScreen(self.service))

    def show_jobs(self) -> None:
        self.switch_screen(JobsScreen(self.service))

    def show_voices(self) -> None:
        try:
            state = self.service.onboarding_state()
        except Exception:
            state = None
        self.switch_screen(VoicesScreen(self.service, state))

    def show_logs(self) -> None:
        self.switch_screen(LogsScreen(self.service))

    def show_job_detail(self, summary: JobSummary) -> None:
        self.push_screen(JobDetailScreen(self.service, summary))

    def show_settings(self) -> None:
        try:
            state = self.service.onboarding_state()
        except Exception:
            return
        self.switch_screen(SettingsScreen(self.service, state))

    def show_onboarding(self) -> None:
        try:
            state = self.service.onboarding_state()
        except Exception:
            return
        self.switch_screen(OnboardingScreen(self.service, state))

    def show_library_settings(self) -> None:
        """Compatibility alias for callers predating persistent navigation."""

        self.show_settings()

    def on_unmount(self) -> None:
        self._shutdown_service()

    def on_exit(self) -> None:
        self._shutdown_service()

    def _shutdown_service(self) -> None:
        if self._shutdown_called:
            return
        self._shutdown_called = True
        with suppress(Exception):
            self.service.shutdown()


__all__ = ["EPUB2M4BApp", "HomeScreen"]
