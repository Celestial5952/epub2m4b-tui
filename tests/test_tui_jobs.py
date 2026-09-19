from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from textual.widgets import Button, Input, ProgressBar, Select, Static, TextArea

from epub2m4b.app.events import ProgressEvent
from epub2m4b.app.jobs import JobSummary
from epub2m4b.app.library import LibraryScan
from epub2m4b.app.onboarding import OnboardingState
from epub2m4b.exceptions import DuplicatePreparationError
from epub2m4b.generation.estimate import NarrationEstimate
from epub2m4b.models import Book, Chapter, JobStatus, NarrationSettings
from epub2m4b.tui.app import EPUB2M4BApp


@dataclass(frozen=True, slots=True)
class Voice:
    id: str
    display_name: str


def _estimate() -> NarrationEstimate:
    return NarrationEstimate(
        word_count=100,
        character_count=600,
        estimated_seconds=300,
        estimated_minutes=Decimal("5"),
        text_input_tokens=150,
        audio_output_tokens=6000,
        estimated_cost_usd=Decimal("1.234567"),
    )


class Service:
    def __init__(self, status: JobStatus = JobStatus.READY, completed: int = 0) -> None:
        self.calls: list[tuple[str, object]] = []
        self.credential_status = "configured"
        self.block_on_controls = False
        self.summary = JobSummary(
            "job-ready",
            "Demo Book",
            ("Ada",),
            status,
            completed,
            2,
            None,
            Path("/jobs/job-ready"),
            narration=NarrationSettings("openai", "gpt-4o-mini-tts", "marin", 1.0, "read"),
        )
        self.fail_estimate = False
        self.book = Book(
            Path("/book.epub"),
            "a" * 64,
            "Demo Book",
            ("Ada",),
            "en",
            None,
            None,
            None,
            None,
            (Chapter(0, "First", None, "", ""), Chapter(1, "Second", None, "", "")),
        )

    def onboarding_state(self) -> OnboardingState:
        return OnboardingState(
            True,
            "marin",
            self.credential_status,
            (),
            (Voice("marin", "Marin"), Voice("nova", "Nova")),
            Path("/tmp/epub-cache"),
            Path("/books"),
            Path("/out"),
            "openai",
            "gpt-4o-mini-tts",
            1.0,
            "Read clearly.",
            25.0,
        )

    async def list_jobs(self) -> tuple[JobSummary, ...]:
        self.calls.append(("list-jobs", None))
        if ("delete-job", self.summary.job_id) in self.calls:
            return ()
        return (self.summary,)

    async def delete_job(self, job_id: str) -> None:
        self.calls.append(("delete-job", job_id))

    async def estimate_job(self, job_id: str) -> NarrationEstimate:
        self.calls.append(("estimate", job_id))
        if self.fail_estimate:
            raise RuntimeError("estimate backend")
        return _estimate()

    async def generate(self, job_id: str, authorized: Decimal):
        self.calls.append(("generate", (job_id, authorized)))
        yield ProgressEvent(job_id, 0, 0, 0, 2, "running")
        if self.block_on_controls:
            import asyncio

            while ("pause", job_id) not in self.calls:
                await asyncio.sleep(0.02)
        self._set_progress(1)
        yield ProgressEvent(job_id, 0, 1, 1, 2, "running")
        if self.block_on_controls:
            import asyncio

            while ("cancel", job_id) not in self.calls:
                await asyncio.sleep(0.02)
        self._set_progress(2)
        yield ProgressEvent(
            job_id,
            None,
            None,
            2,
            2,
            "complete: /out/Demo Book.m4b",
            output_path="/out/Demo Book.m4b",
        )

    def _set_progress(self, completed: int) -> None:
        self.summary = JobSummary(
            self.summary.job_id,
            self.summary.title,
            self.summary.authors,
            JobStatus.COMPLETE if completed >= self.summary.total_chunks else self.summary.status,
            completed,
            self.summary.total_chunks,
            self.summary.updated_at,
            self.summary.path,
            narration=self.summary.narration,
        )

    async def pause(self, job_id: str) -> None:
        self.calls.append(("pause", job_id))

    async def cancel(self, job_id: str) -> None:
        self.calls.append(("cancel", job_id))

    def open_audiobook(self, path: Path) -> None:
        self.calls.append(("open", path))

    async def inspect_book(self, source: Path) -> object:
        self.calls.append(("inspect", source))
        return self.book

    async def scan_book_folder(self) -> LibraryScan:
        return LibraryScan(None, ())

    async def create_job(self, source: Path) -> object:
        raise DuplicatePreparationError("job-existing")

    def complete_onboarding(
        self,
        voice_id: str,
        cache_directory: Path | None = None,
        book_directory: Path | None = None,
        **kwargs: object,
    ) -> None:
        self.calls.append(
            ("complete", (voice_id, cache_directory, book_directory, kwargs))
        )

    def remove_openai_credential(self) -> None:
        self.calls.append(("remove-credential", None))

    def skip_onboarding(self) -> None: ...
    def set_openai_credential(self, secret: str) -> None: ...
    def play_voice_preview(self, voice_id: str) -> None: ...
    def stop_voice_preview(self) -> None:
        self.calls.append(("stop-preview", None))
    def shutdown(self) -> None: ...

    async def estimate_job_preview(self, job_id: str) -> NarrationEstimate:
        self.calls.append(("estimate-preview", job_id))
        return NarrationEstimate(
            word_count=20,
            character_count=100,
            estimated_seconds=30,
            estimated_minutes=Decimal("0.5"),
            text_input_tokens=25,
            audio_output_tokens=500,
            estimated_cost_usd=Decimal("0.02"),
        )

    async def generate_job_preview(self, job_id: str, authorized: Decimal) -> Path:
        self.calls.append(("generate-preview", (job_id, authorized)))
        self._preview_path = Path(f"/previews/preview-{job_id}.wav")
        return self._preview_path

    def get_job_preview(self, job_id: str) -> Path | None:
        return getattr(self, "_preview_path", None)

    def play_audio_file(self, path: Path) -> None:
        self.calls.append(("play-audio", path))


@pytest.mark.asyncio
async def test_jobs_card_opens_detail_with_estimate() -> None:
    service = Service()
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-jobs")
        await pilot.pause(0.3)
        assert app.screen.__class__.__name__ == "JobsScreen"
        await pilot.click("#view-job-ready")
        await pilot.pause(0.5)
        assert app.screen.__class__.__name__ == "JobDetailScreen"
        title = str(app.screen.query_one("#detail-title", Static).renderable)
        info = str(app.screen.query_one("#detail-info", Static).renderable)
        estimate = str(app.screen.query_one("#detail-estimate", Static).renderable)
        status = str(app.screen.query_one("#detail-status", Static).renderable)
        assert "Demo Book" in title
        assert "openai" in info and "marin" in info
        assert "Remaining estimate: $1.24" in estimate
        assert "0 of 2" in status
        start = app.screen.query_one("#start-narrating", Button)
        assert not start.disabled
        assert app.screen.query_one("#open-audiobook", Button).disabled
        assert ("estimate", "job-ready") in service.calls


@pytest.mark.asyncio
async def test_delete_old_job_requires_confirmation_and_refreshes_list() -> None:
    service = Service()
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-jobs")
        await pilot.pause(0.3)
        delete = app.screen.query_one("#delete-job-ready", Button)
        delete.scroll_visible()
        await pilot.pause(0.2)
        await pilot.click("#delete-job-ready")
        await pilot.pause(0.2)
        assert app.screen.__class__.__name__ == "DeleteJobScreen"
        await pilot.click("#delete-job-confirm")
        await pilot.pause(0.5)

        assert ("delete-job", "job-ready") in service.calls
        assert app.screen.__class__.__name__ == "JobsScreen"
        status = app.screen.query_one("#jobs-status", Static)
        assert "Old job deleted" in str(status.renderable)


@pytest.mark.asyncio
async def test_confirmation_boundary_requires_typed_start() -> None:
    service = Service()
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-jobs")
        await pilot.pause(0.3)
        await pilot.click("#view-job-ready")
        await pilot.pause(0.5)
        await pilot.click("#start-narrating")
        await pilot.pause(0.5)
        assert app.screen.__class__.__name__ == "ConfirmGenerationScreen"
        heading = str(app.screen.query_one("#confirm-heading", Static).renderable)
        body = str(app.screen.query_one("#confirm-estimate", Static).renderable)
        assert "spends money" in heading
        assert "$1.24" in body and "15% safety margin" in body
        confirm = app.screen.query_one("#confirm-start", Button)
        assert confirm.disabled
        # Typing the wrong word must not unlock the paid action.
        app.screen.query_one("#confirm-input", Input).value = "GO"
        await pilot.pause(0.2)
        assert app.screen.query_one("#confirm-start", Button).disabled
        app.screen.query_one("#confirm-input", Input).value = "start"
        await pilot.pause(0.2)
        assert not app.screen.query_one("#confirm-start", Button).disabled
        await pilot.click("#confirm-cancel")
        await pilot.pause(0.3)
        assert app.screen.__class__.__name__ == "JobDetailScreen"
        assert not any(name == "generate" for name, _ in service.calls)


@pytest.mark.asyncio
async def test_confirmed_generation_updates_progress_and_opens_audiobook() -> None:
    service = Service()
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-jobs")
        await pilot.pause(0.3)
        await pilot.click("#view-job-ready")
        await pilot.pause(0.5)
        await pilot.click("#start-narrating")
        await pilot.pause(0.5)
        app.screen.query_one("#confirm-input", Input).value = "START"
        await pilot.pause(0.2)
        await pilot.click("#confirm-start")
        await pilot.pause(1.0)
        assert app.screen.__class__.__name__ == "JobDetailScreen"
        assert ("generate", ("job-ready", Decimal("1.234567"))) in service.calls
        progress = app.screen.query_one("#detail-progress", ProgressBar)
        assert progress.completed == 2 and progress.total == 2
        open_button = app.screen.query_one("#open-audiobook", Button)
        assert not open_button.disabled
        message = str(app.screen.query_one("#detail-message", Static).renderable)
        assert "Finished" in message
        await pilot.click("#open-audiobook")
        await pilot.pause(0.3)
        assert ("open", Path("/out/Demo Book.m4b")) in service.calls
        start = app.screen.query_one("#start-narrating", Button)
        assert start.disabled


@pytest.mark.asyncio
async def test_narration_continues_after_navigating_away_from_job_screen() -> None:
    service = Service()
    service.block_on_controls = True
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-jobs")
        await pilot.pause(0.3)
        await pilot.click("#view-job-ready")
        await pilot.pause(0.3)
        await pilot.click("#start-narrating")
        await pilot.pause(0.3)
        app.screen.query_one("#confirm-input", Input).value = "START"
        await pilot.pause(0.2)
        await pilot.click("#confirm-start")
        await pilot.pause(0.3)

        await pilot.click("#nav-settings")
        await pilot.pause(0.3)
        assert app.screen.__class__.__name__ == "SettingsScreen"

        # Release both fake chunk boundaries while the detail screen is gone.
        await service.pause("job-ready")
        await pilot.pause(0.2)
        await service.cancel("job-ready")
        for _ in range(50):
            if service.summary.completed_chunks == 2:
                break
            await pilot.pause(0.05)

        assert service.summary.completed_chunks == 2


@pytest.mark.asyncio
async def test_pause_and_cancel_signal_the_service_only_while_running() -> None:
    service = Service()
    service.block_on_controls = True
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-jobs")
        await pilot.pause(0.3)
        await pilot.click("#view-job-ready")
        await pilot.pause(0.5)
        pause = app.screen.query_one("#pause-job", Button)
        cancel = app.screen.query_one("#cancel-job", Button)
        assert not pause.display and not cancel.display
        await pilot.click("#start-narrating")
        await pilot.pause(0.5)
        app.screen.query_one("#confirm-input", Input).value = "START"
        await pilot.pause(0.2)
        await pilot.click("#confirm-start")
        await pilot.pause(0.5)
        assert app.screen.query_one("#pause-job", Button).display
        await pilot.click("#pause-job")
        for _ in range(50):
            if ("pause", "job-ready") in service.calls:
                break
            await pilot.pause(0.05)
        assert ("pause", "job-ready") in service.calls
        await pilot.click("#cancel-job")
        for _ in range(50):
            if ("cancel", "job-ready") in service.calls:
                break
            await pilot.pause(0.05)
        assert ("cancel", "job-ready") in service.calls
        await pilot.pause(1.0)


@pytest.mark.asyncio
async def test_estimate_failure_disables_start_with_clear_message() -> None:
    service = Service()
    service.fail_estimate = True
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-jobs")
        await pilot.pause(0.3)
        await pilot.click("#view-job-ready")
        await pilot.pause(0.5)
        start = app.screen.query_one("#start-narrating", Button)
        assert start.disabled


@pytest.mark.asyncio
async def test_back_to_jobs_navigation() -> None:
    service = Service()
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-jobs")
        await pilot.pause(0.3)
        await pilot.click("#view-job-ready")
        await pilot.pause(0.5)
        await pilot.click("#back-jobs")
        await pilot.pause(0.3)
        assert app.screen.__class__.__name__ == "JobsScreen"


@pytest.mark.asyncio
async def test_settings_saves_full_surface_and_removes_credential() -> None:
    service = Service()
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-settings")
        await pilot.pause(0.3)
        screen = app.screen
        assert screen.query_one("#settings-output-directory", Input).value == "/out"
        assert screen.query_one("#settings-speed", Input).value == "1.0"
        assert screen.query_one("#settings-cost-cap", Input).value == "25.0"
        assert screen.query_one("#settings-instructions", TextArea).text == "Read clearly."
        assert not screen.query_one("#settings-remove-credential", Button).disabled
        screen.query_one("#settings-output-directory", Input).value = "/new-out"
        screen.query_one("#settings-speed", Input).value = "1.1"
        screen.query_one("#settings-cost-cap", Input).value = "30"
        screen.query_one("#settings-instructions", TextArea).text = "Read slowly."
        screen.query_one("#settings-model", Select).value = "gpt-4o-mini-tts"
        await pilot.click("#save-settings")
        await pilot.pause(0.3)
        saved = (
            "complete",
            (
                "marin",
                Path("/tmp/epub-cache"),
                Path("/books"),
                {
                    "output_directory": Path("/new-out"),
                    "provider": "openai",
                    "model": "gpt-4o-mini-tts",
                    "speed": 1.1,
                    "instructions": "Read slowly.",
                    "maximum_estimated_cost_usd": 30.0,
                },
            ),
        )
        assert saved in service.calls
        remove = app.screen.query_one("#settings-remove-credential", Button)
        remove.scroll_visible()
        await pilot.pause(0.3)
        await pilot.click("#settings-remove-credential")
        await pilot.pause(0.5)
        assert ("remove-credential", None) in service.calls


@pytest.mark.asyncio
async def test_settings_refuse_untested_elevenlabs_provider() -> None:
    service = Service()
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-settings")
        await pilot.pause(0.3)
        app.screen.query_one("#settings-provider", Select).value = "elevenlabs"
        await pilot.click("#save-settings")
        await pilot.pause(0.3)
        message = str(app.screen.query_one("#settings-message", Static).renderable)
        assert "UNTESTED" in message
        assert not any(name == "complete" for name, _ in service.calls)


@pytest.mark.asyncio
async def test_settings_reject_non_numeric_speed_and_cap() -> None:
    service = Service()
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-settings")
        await pilot.pause(0.3)
        app.screen.query_one("#settings-speed", Input).value = "fast"
        await pilot.click("#save-settings")
        await pilot.pause(0.2)
        message = str(app.screen.query_one("#settings-message", Static).renderable)
        assert "speed" in message.lower()
        assert not any(name == "complete" for name, _ in service.calls)


@pytest.mark.asyncio
async def test_duplicate_preparation_message_points_to_jobs() -> None:
    service = Service()
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        field = app.screen.query_one("#source-path", Input)
        field.value = "/books/demo.epub"
        await pilot.click("#inspect")
        await pilot.pause(0.3)
        await pilot.click("#prepare")
        await pilot.pause(0.5)
        status = str(app.screen.query_one("#status", Static).renderable)
        assert "already set up" in status
        assert "job-existing" in status
        assert app.screen.query_one("#prepare", Button).disabled


@pytest.mark.asyncio
async def test_mouse_navigation_survives_80x24_terminal() -> None:
    service = Service()
    app = EPUB2M4BApp(service)
    async with app.run_test(size=(80, 24)) as pilot:
        assert app.screen.__class__.__name__ == "HomeScreen"
        await pilot.click("#nav-jobs")
        await pilot.pause(0.3)
        assert app.screen.__class__.__name__ == "JobsScreen"
        await pilot.click("#nav-settings")
        await pilot.pause(0.3)
        assert app.screen.__class__.__name__ == "SettingsScreen"
        await pilot.click("#nav-library")
        await pilot.pause(0.3)
        assert app.screen.__class__.__name__ == "HomeScreen"


@pytest.mark.asyncio
async def test_job_detail_nav_buttons_navigate() -> None:
    service = Service()
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-jobs")
        await pilot.pause(0.3)
        await pilot.click("#view-job-ready")
        await pilot.pause(0.5)
        assert app.screen.__class__.__name__ == "JobDetailScreen"

        # Navigate to logs
        await pilot.click("#nav-logs")
        await pilot.pause(0.3)
        assert app.screen.__class__.__name__ == "LogsScreen"

        # Navigate to settings
        await pilot.click("#nav-settings")
        await pilot.pause(0.3)
        assert app.screen.__class__.__name__ == "SettingsScreen"

        # Go back to jobs and detail, then use back-jobs
        await pilot.click("#nav-jobs")
        await pilot.pause(0.3)
        await pilot.click("#view-job-ready")
        await pilot.pause(0.5)
        assert app.screen.__class__.__name__ == "JobDetailScreen"

        await pilot.click("#back-jobs")
        await pilot.pause(0.3)
        assert app.screen.__class__.__name__ == "JobsScreen"


@pytest.mark.asyncio
async def test_job_detail_preview_sample_flow_and_playback() -> None:
    service = Service()
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-jobs")
        await pilot.pause(0.3)
        await pilot.click("#view-job-ready")
        await pilot.pause(0.5)
        assert app.screen.__class__.__name__ == "JobDetailScreen"

        # Initially play and stop buttons are disabled
        play_sample_btn = app.screen.query_one("#play-sample", Button)
        assert play_sample_btn.disabled is True

        # Click Generate 30s sample
        preview_btn = app.screen.query_one("#preview-sample", Button)
        preview_btn.scroll_visible()
        await pilot.pause(0.2)
        await pilot.click("#preview-sample")
        await pilot.pause(0.3)

        # Modal should appear
        assert app.screen.__class__.__name__ == "ConfirmPreviewScreen"
        heading = app.screen.query_one("#confirm-preview-heading", Static)
        assert "Generate Narration Sample" in str(heading.renderable)

        # Confirm sample generation
        await pilot.click("#confirm-preview-start")
        await pilot.pause(0.5)

        # Detail screen should now have play sample enabled
        assert ("estimate-preview", "job-ready") in service.calls
        assert any(call[0] == "generate-preview" and call[1][0] == "job-ready" for call in service.calls)

        play_sample_btn = app.screen.query_one("#play-sample", Button)
        assert play_sample_btn.disabled is False

        # Click Play sample
        await pilot.click("#play-sample")
        await pilot.pause(0.2)
        assert any(call[0] == "play-audio" for call in service.calls)

        # Click Stop sample
        await pilot.click("#stop-sample")
        await pilot.pause(0.2)
        assert ("stop-preview", None) in service.calls


