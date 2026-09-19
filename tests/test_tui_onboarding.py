from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from textual.widgets import Input, Static

from epub2m4b.app.onboarding import OnboardingState
from epub2m4b.tui.app import EPUB2M4BApp


@dataclass(frozen=True, slots=True)
class Voice:
    id: str
    display_name: str


class FakeService:
    def __init__(self, completed: bool = False) -> None:
        self.calls: list[tuple[str, object]] = []
        self.state = OnboardingState(
            completed=completed,
            selected_voice="marin",
            credential_status="unconfigured",
            dependencies=("ffmpeg: available", "ffprobe: available", "ffplay: available"),
            voices=(Voice("marin", "Marin"), Voice("nova", "Nova")),
            cache_directory=Path("/tmp/epub-cache"),
            book_directory=Path("/tmp/books"),
        )

    def onboarding_state(self) -> OnboardingState:
        return self.state

    def complete_onboarding(
        self,
        voice_id: str,
        cache_directory: Path | None = None,
        book_directory: Path | None = None,
    ) -> None:
        self.calls.append(("complete", (voice_id, cache_directory, book_directory)))

    def skip_onboarding(self) -> None:
        self.calls.append(("skip", None))

    def set_openai_credential(self, secret: str) -> None:
        self.calls.append(("set", secret))

    def remove_openai_credential(self) -> None:
        self.calls.append(("remove", None))

    def play_voice_preview(self, voice_id: str) -> None:
        self.calls.append(("play", voice_id))

    def stop_voice_preview(self) -> None:
        self.calls.append(("stop", None))

    def shutdown(self) -> None:
        self.calls.append(("shutdown", None))


@pytest.mark.asyncio
async def test_startup_routes_to_onboarding_or_home() -> None:
    service = FakeService()
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        assert app.screen.__class__.__name__ == "OnboardingScreen"
        await pilot.press("escape")
    assert ("shutdown", None) in service.calls

    complete = FakeService(completed=True)
    async with EPUB2M4BApp(complete).run_test():
        assert complete.calls == []


@pytest.mark.asyncio
async def test_skip_leaves_onboarding() -> None:
    service = FakeService()
    async with EPUB2M4BApp(service).run_test() as pilot:
        await pilot.click("#skip")
        assert ("skip", None) in service.calls
        assert app_screen_name(pilot) == "HomeScreen"


@pytest.mark.asyncio
async def test_voice_selection_and_play_stop_delegate() -> None:
    service = FakeService()
    async with EPUB2M4BApp(service).run_test() as pilot:
        await click_next(pilot)
        await click_next(pilot)
        await click_next(pilot)
        await pilot.click("#voice-select")
        await pilot.press("n")
        await pilot.press("enter")
        await pilot.click("#play-nova")
        await pilot.click("#stop-nova")
    assert ("play", "nova") in service.calls
    assert ("stop", None) in service.calls


@pytest.mark.asyncio
async def test_masked_key_is_saved_and_cleared() -> None:
    service = FakeService()
    async with EPUB2M4BApp(service).run_test() as pilot:
        await click_next(pilot)
        await click_next(pilot)
        await click_next(pilot)
        await click_next(pilot)
        field = pilot.app.screen.query_one("#api-key-input", Input)
        assert field.password is True
        field.value = "test-secret"
        await pilot.click("#save-key")
        await pilot.pause(0.5)
        assert field.value == ""
    assert ("set", "test-secret") in service.calls


@pytest.mark.asyncio
async def test_finish_selected_voice_and_shutdown() -> None:
    service = FakeService()
    async with EPUB2M4BApp(service).run_test() as pilot:
        for _ in range(6):
            await click_next(pilot)
        assert (
            "complete",
            ("marin", Path("/tmp/epub-cache"), Path("/tmp/books")),
        ) in service.calls
        assert app_screen_name(pilot) == "HomeScreen"


@pytest.mark.asyncio
async def test_storage_fields_are_editable_and_passed_on_finish() -> None:
    service = FakeService()
    async with EPUB2M4BApp(service).run_test() as pilot:
        await click_next(pilot)
        await click_next(pilot)
        cache = pilot.app.screen.query_one("#cache-directory", Input)
        books = pilot.app.screen.query_one("#book-directory", Input)
        assert cache.value == "/tmp/epub-cache"
        assert books.value == "/tmp/books"
        cache.value = "/mnt/ssd/cache"
        books.value = "/mnt/ssd/books"
        for _ in range(4):
            await click_next(pilot)
    assert (
        "complete",
        ("marin", Path("/mnt/ssd/cache"), Path("/mnt/ssd/books")),
    ) in service.calls


@pytest.mark.asyncio
async def test_storage_browse_opens_directory_picker_and_can_cancel() -> None:
    service = FakeService()
    async with EPUB2M4BApp(service).run_test() as pilot:
        await click_next(pilot)
        await click_next(pilot)
        original = pilot.app.screen.query_one("#cache-directory", Input).value
        await pilot.click("#browse-cache")
        await pilot.pause(0.2)
        assert pilot.app.screen.__class__.__name__ == "DirectoryPickerScreen"
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert pilot.app.screen.__class__.__name__ == "OnboardingScreen"
        assert pilot.app.screen.query_one("#cache-directory", Input).value == original


@pytest.mark.asyncio
async def test_first_screen_reassures_non_terminal_users() -> None:
    service = FakeService()
    async with EPUB2M4BApp(service).run_test() as pilot:
        welcome = str(pilot.app.screen.query_one("#welcome-step Static", Static).renderable)
        title = str(pilot.app.screen.query_one("#step-title", Static).renderable)
        assert "do not need to know any terminal commands" in welcome
        assert "Step 1 of 6" in title


def app_screen_name(pilot: object) -> str:
    return pilot.app.screen.__class__.__name__  # type: ignore[attr-defined]


async def click_next(pilot: object) -> None:
    await pilot.click("#next")  # type: ignore[attr-defined]
    await pilot.pause(0.5)  # type: ignore[attr-defined]
