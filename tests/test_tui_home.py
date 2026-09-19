from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Button, Input, Select, Static

from epub2m4b.app.jobs import JobSummary
from epub2m4b.app.library import LibraryBook, LibraryScan
from epub2m4b.app.onboarding import OnboardingState
from epub2m4b.models import Book, Chapter, JobStatus
from epub2m4b.tui.app import EPUB2M4BApp


class Voice:
    id = "marin"
    display_name = "Marin"


class Job:
    job_id = "job-123"


class Service:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.fail = False
        self.book = Book(
            Path("/book.epub"), "a" * 64, "Demo Book", ("Ada", "Grace"), "en", None,
            None, None, None, (Chapter(0, "First", None, "", ""), Chapter(1, "Second", None, "", "")),
        )
        self.jobs = (
            JobSummary(
                "job-ready",
                "Demo Book",
                ("Ada",),
                JobStatus.READY,
                0,
                10,
                None,
                Path("/jobs/job-ready"),
            ),
        )

    def onboarding_state(self) -> OnboardingState:
        return OnboardingState(
            True,
            "marin",
            "unconfigured",
            (),
            (Voice(),),
            Path("/tmp/epub-cache"),
            Path("/books"),
        )

    async def inspect_book(self, source: Path) -> Book:
        self.calls.append(("inspect", source))
        if self.fail:
            raise RuntimeError("private book text")
        return self.book

    async def scan_book_folder(self) -> LibraryScan:
        self.calls.append(("scan", None))
        root = Path("/books")
        return LibraryScan(
            root,
            (
                LibraryBook(root / "Ada" / "demo.epub", Path("Ada/demo.epub")),
                LibraryBook(root / "Other.epub", Path("Other.epub")),
            ),
        )

    async def create_job(self, source: Path) -> Job:
        self.calls.append(("prepare", source))
        return Job()

    async def list_jobs(self) -> tuple[JobSummary, ...]:
        self.calls.append(("list-jobs", None))
        return self.jobs

    def shutdown(self) -> None: ...

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

    def skip_onboarding(self) -> None:
        self.calls.append(("skip", None))
    def set_openai_credential(self, secret: str) -> None: ...
    def play_voice_preview(self, voice_id: str) -> None: ...
    def stop_voice_preview(self) -> None: ...


async def start(service: Service):
    app = EPUB2M4BApp(service)
    context = app.run_test()
    pilot = await context.__aenter__()
    return app, context, pilot


async def inspect(app, pilot, value: str) -> None:
    app.screen.query_one("#source-path", Input).value = value
    await pilot.click("#inspect")
    await pilot.pause(0.5)


@pytest.mark.asyncio
async def test_completed_startup_inspection_renders_stable_book_order() -> None:
    service = Service()
    app, context, pilot = await start(service)
    try:
        assert app.screen.__class__.__name__ == "HomeScreen"
        await inspect(app, pilot, "/books/demo.epub")
        summary = str(app.screen.query_one("#book-summary", Static).renderable)
        chapters = str(app.screen.query_one("#chapter-list", Static).renderable)
        assert "Demo Book" in summary and "Ada, Grace" in summary and "2" in summary
        assert chapters.index("First") < chapters.index("Second")
    finally:
        await context.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_prepare_delegates_same_source() -> None:
    service = Service()
    app, context, pilot = await start(service)
    try:
        await inspect(app, pilot, "/books/demo.epub")
        await pilot.click("#prepare")
        await pilot.pause(0.5)
        await pilot.click("#prepare")
        await pilot.pause(0.2)
        assert service.calls == [
            ("scan", None),
            ("inspect", Path("/books/demo.epub")),
            ("prepare", Path("/books/demo.epub")),
        ]
        assert "job-123" in str(app.screen.query_one("#status", Static).renderable)
        assert app.screen.query_one("#prepare", Button).disabled
    finally:
        await context.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_library_scan_populates_select_and_selection_updates_path() -> None:
    service = Service()
    app, context, pilot = await start(service)
    try:
        selector = app.screen.query_one("#library-select", Select)
        assert not selector.disabled
        selector.value = "/books/Ada/demo.epub"
        await pilot.pause(0.2)
        selected = app.screen.query_one("#source-path", Input).value
        assert selected in {"/books/Ada/demo.epub", "/books/Other.epub"}
        assert service.calls == [("scan", None), ("inspect", Path(selected))]
        assert "Book ready" in str(app.screen.query_one("#status", Static).renderable)
    finally:
        await context.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_navigation_opens_direct_settings_without_replaying_onboarding() -> None:
    service = Service()
    app, context, pilot = await start(service)
    try:
        await pilot.click("#nav-settings")
        await pilot.pause(0.2)
        assert app.screen.__class__.__name__ == "SettingsScreen"
        assert app.screen.query_one("#settings-book-directory", Input).value == "/books"
        assert app.screen.query_one("#settings-cache-directory", Input).value == "/tmp/epub-cache"
        assert not any(name in {"complete", "skip"} for name, _ in service.calls)
    finally:
        await context.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_settings_save_and_library_navigation_rescan() -> None:
    service = Service()
    app, context, pilot = await start(service)
    try:
        await pilot.click("#nav-settings")
        await pilot.pause(0.2)
        app.screen.query_one("#settings-book-directory", Input).value = "/new-books"
        app.screen.query_one("#settings-cache-directory", Input).value = "/new-cache"
        await pilot.click("#save-settings")
        await pilot.pause(0.2)
        assert app.screen.__class__.__name__ == "SettingsScreen"
        assert "saved" in str(app.screen.query_one("#settings-message", Static).renderable)
        await pilot.click("#nav-library")
        await pilot.pause(0.2)
        assert app.screen.__class__.__name__ == "HomeScreen"
        saved = (
            "complete",
            (
                "marin",
                Path("/new-cache"),
                Path("/new-books"),
                {
                    "output_directory": None,
                    "provider": "openai",
                    "model": "gpt-4o-mini-tts",
                    "speed": 1.0,
                    "instructions": "",
                    "maximum_estimated_cost_usd": 25.0,
                },
            ),
        )
        assert saved in service.calls
        assert service.calls.count(("scan", None)) == 2
    finally:
        await context.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_jobs_navigation_explains_ready_means_no_credits_used() -> None:
    service = Service()
    app, context, pilot = await start(service)
    try:
        await pilot.click("#nav-jobs")
        await pilot.pause(0.2)
        assert app.screen.__class__.__name__ == "JobsScreen"
        summaries = [
            str(widget.renderable)
            for widget in app.screen.query(".job-summary")
        ]
        content = "\n".join(summaries)
        help_text = str(app.screen.query_one("#jobs-help", Static).renderable)
        assert "Demo Book" in content
        assert "Ready — no narration started" in content
        assert "0 of 10" in content
        assert "not used credits" in help_text
        assert ("list-jobs", None) in service.calls
    finally:
        await context.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_blank_and_error_are_generic_and_clear_stale_state() -> None:
    service = Service()
    app, context, pilot = await start(service)
    try:
        await inspect(app, pilot, "/books/demo.epub")
        field = app.screen.query_one("#source-path", Input)
        field.value = ""
        await pilot.click("#inspect")
        await pilot.pause(0.2)
        assert app.screen.query_one("#prepare", Button).disabled
        assert "Demo Book" not in str(app.screen.query_one("#book-summary", Static).renderable)
        service.fail = True
        await inspect(app, pilot, "/private/secret.epub")
        message = str(app.screen.query_one("#status", Static).renderable)
        assert "could not" in message and "private" not in message and "secret" not in message
    finally:
        await context.__aexit__(None, None, None)
