from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from textual.widgets import Button, Static

from epub2m4b.app.onboarding import OnboardingState
from epub2m4b.tui.app import EPUB2M4BApp
from epub2m4b.tui.voices import VoicesScreen


@dataclass(frozen=True, slots=True)
class FakeVoiceEntry:
    id: str
    display_name: str
    duration_seconds: float = 12.3
    size_bytes: int = 1024
    sha256: str = "0" * 64


class FakeVoicesService:
    def __init__(self, selected_voice: str = "marin") -> None:
        self.calls: list[tuple[str, object]] = []
        self.selected_voice = selected_voice
        self.voices = (
            FakeVoiceEntry("marin", "Marin", 14.5),
            FakeVoiceEntry("alloy", "Alloy", 12.0),
            FakeVoiceEntry("echo", "Echo", 13.2),
        )
        self.fail_play = False
        self.fail_save = False

    def onboarding_state(self) -> OnboardingState:
        return OnboardingState(
            completed=True,
            selected_voice=self.selected_voice,
            credential_status="configured",
            dependencies=(),
            voices=self.voices,
            cache_directory=Path("/tmp/epub-cache"),
            book_directory=Path("/books"),
            output_directory=Path("/audiobooks"),
            provider="openai",
            model="gpt-4o-mini-tts",
            speed=1.0,
            instructions="",
            maximum_estimated_cost_usd=25.0,
        )

    def play_voice_preview(self, voice_id: str) -> None:
        self.calls.append(("play", voice_id))
        if self.fail_play:
            raise RuntimeError("audio error")

    def stop_voice_preview(self) -> None:
        self.calls.append(("stop", None))

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
        if self.fail_save:
            raise RuntimeError("save error")
        self.selected_voice = voice_id

    def shutdown(self) -> None:
        pass


@pytest.mark.asyncio
async def test_voices_navigation_renders_voice_cards() -> None:
    service = FakeVoicesService(selected_voice="marin")
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-voices")
        await pilot.pause(0.2)
        assert isinstance(app.screen, VoicesScreen)

        # Check titles and cards
        title = app.screen.query_one("#voices-title", Static)
        assert "Voice auditions" in str(title.renderable)

        marin_title = app.screen.query_one("#voice-title-marin", Static)
        assert "Marin" in str(marin_title.renderable)
        assert "Default Voice" in str(marin_title.renderable)

        alloy_title = app.screen.query_one("#voice-title-alloy", Static)
        assert "Alloy" in str(alloy_title.renderable)
        assert "Default Voice" not in str(alloy_title.renderable)

        # Check button states
        marin_select = app.screen.query_one("#select-marin", Button)
        assert marin_select.disabled is True

        alloy_select = app.screen.query_one("#select-alloy", Button)
        assert alloy_select.disabled is False


@pytest.mark.asyncio
async def test_voices_play_and_stop_controls() -> None:
    service = FakeVoicesService(selected_voice="marin")
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-voices")
        await pilot.pause(0.2)

        # Play alloy
        play_btn = app.screen.query_one("#play-alloy", Button)
        play_btn.scroll_visible()
        await pilot.pause(0.2)
        await pilot.click("#play-alloy")
        await pilot.pause(0.2)
        assert ("play", "alloy") in service.calls
        status = app.screen.query_one("#voices-status", Static)
        assert "Playing audition for Alloy" in str(status.renderable)

        # Stop alloy
        stop_btn = app.screen.query_one("#stop-alloy", Button)
        stop_btn.scroll_visible()
        await pilot.pause(0.2)
        await pilot.click("#stop-alloy")
        await pilot.pause(0.2)
        assert ("stop", None) in service.calls
        assert "Playback stopped" in str(status.renderable)

        # Stop all button
        stop_all_btn = app.screen.query_one("#stop-all", Button)
        stop_all_btn.scroll_visible()
        await pilot.pause(0.2)
        await pilot.click("#stop-all")
        await pilot.pause(0.2)
        assert service.calls.count(("stop", None)) >= 2


@pytest.mark.asyncio
async def test_voices_set_default_updates_state_and_cards() -> None:
    service = FakeVoicesService(selected_voice="marin")
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-voices")
        await pilot.pause(0.2)

        # Set alloy as default
        select_btn = app.screen.query_one("#select-alloy", Button)
        select_btn.scroll_visible()
        await pilot.pause(0.2)
        await pilot.click("#select-alloy")
        await pilot.pause(0.3)

        assert any(call[0] == "complete" and call[1][0] == "alloy" for call in service.calls)

        status = app.screen.query_one("#voices-status", Static)
        assert "Alloy set as default" in str(status.renderable)

        # Alloy card should now have default badge and disabled select button
        alloy_title = app.screen.query_one("#voice-title-alloy", Static)
        assert "Default Voice" in str(alloy_title.renderable)

        alloy_select = app.screen.query_one("#select-alloy", Button)
        assert alloy_select.disabled is True

        # Marin should now be selectable
        marin_select = app.screen.query_one("#select-marin", Button)
        assert marin_select.disabled is False


@pytest.mark.asyncio
async def test_voices_navigation_to_other_screens() -> None:
    service = FakeVoicesService(selected_voice="marin")
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-voices")
        await pilot.pause(0.2)
        assert isinstance(app.screen, VoicesScreen)

        # Navigate to Settings
        await pilot.click("#nav-settings")
        await pilot.pause(0.2)
        assert app.screen.__class__.__name__ == "SettingsScreen"

        # Navigate back to Voices
        await pilot.click("#nav-voices")
        await pilot.pause(0.2)
        assert isinstance(app.screen, VoicesScreen)

        # Navigate to Logs
        await pilot.click("#nav-logs")
        await pilot.pause(0.2)
        assert app.screen.__class__.__name__ == "LogsScreen"

        # Navigate back to Voices
        await pilot.click("#nav-voices")
        await pilot.pause(0.2)
        assert isinstance(app.screen, VoicesScreen)

        # Navigate to Library
        await pilot.click("#nav-library")
        await pilot.pause(0.2)
        assert app.screen.__class__.__name__ == "HomeScreen"


@pytest.mark.asyncio
async def test_voices_play_error_handling() -> None:
    service = FakeVoicesService(selected_voice="marin")
    service.fail_play = True
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-voices")
        await pilot.pause(0.2)

        play_btn = app.screen.query_one("#play-alloy", Button)
        play_btn.scroll_visible()
        await pilot.pause(0.2)
        await pilot.click("#play-alloy")
        await pilot.pause(0.2)
        status = app.screen.query_one("#voices-status", Static)
        assert "Could not play" in str(status.renderable)
