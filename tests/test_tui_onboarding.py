from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from textual.widgets import Input, Select, Static

from epub2m4b.app.onboarding import OnboardingState, ProviderOption, provider_options
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

    def set_provider_credential(self, provider_id: str, secret: str) -> None:
        self.calls.append(("set", (provider_id, secret)))

    def remove_provider_credential(self, provider_id: str) -> None:
        self.calls.append(("remove", provider_id))

    def set_openai_credential(self, secret: str) -> None:
        self.calls.append(("set-openai", secret))

    def remove_openai_credential(self) -> None:
        self.calls.append(("remove-openai", None))

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
        await go_to_key_step(pilot)
        field = pilot.app.screen.query_one("#api-key-input", Input)
        assert field.password is True
        assert "OpenAI" in field.placeholder
        field.value = "test-secret"
        await pilot.click("#save-key")
        await pilot.pause(0.5)
        assert field.value == ""
    assert ("set", ("openai", "test-secret")) in service.calls


@pytest.mark.asyncio
async def test_finish_selected_voice_and_shutdown() -> None:
    service = FakeService()
    async with EPUB2M4BApp(service).run_test() as pilot:
        for _ in range(7):
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
        for _ in range(5):
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
        assert "Step 1 of 7" in title


async def go_to_key_step(pilot: object) -> None:
    for _ in range(5):
        await click_next(pilot)


async def go_to_provider_step(pilot: object) -> None:
    for _ in range(4):
        await click_next(pilot)


def _screen_text(pilot: object, selector: str) -> str:
    return str(pilot.app.screen.query_one(selector, Static).renderable)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_provider_step_lists_registry_providers_with_openai_selected() -> None:
    async with EPUB2M4BApp(FakeService()).run_test() as pilot:
        await go_to_provider_step(pilot)
        title = _screen_text(pilot, "#step-title")
        select = pilot.app.screen.query_one("#provider-select", Select)
        assert "Narration service" in title and "Step 5 of 7" in title
        assert select.value == "openai"
        labels = [str(prompt) for prompt, _ in select._options if prompt is not Select.BLANK]
        assert labels == ["OpenAI (verified)", "ElevenLabs (UNTESTED live)"]
        assert "OpenAI reads your books aloud" in _screen_text(pilot, "#provider-info")


@pytest.mark.asyncio
async def test_choosing_an_untested_provider_asks_for_its_own_key_and_keeps_narration_safe() -> (
    None
):
    service = FakeService()
    async with EPUB2M4BApp(service).run_test() as pilot:
        await go_to_provider_step(pilot)
        pilot.app.screen.query_one("#provider-select", Select).value = "elevenlabs"
        await pilot.pause(0.2)
        info = _screen_text(pilot, "#provider-info")
        assert "not been tested live" in info
        assert "narration keeps using OpenAI" in info

        await click_next(pilot)  # key step now speaks about ElevenLabs
        field = pilot.app.screen.query_one("#api-key-input", Input)
        key_info = _screen_text(pilot, "#key-provider-info")
        assert field.placeholder == "Paste your ElevenLabs API key"
        assert "https://elevenlabs.io/app/settings/api-keys" in key_info
        assert "No ElevenLabs key is saved yet." in key_info
        field.value = "el-secret"
        await pilot.click("#save-key")
        await pilot.pause(0.3)
        assert field.value == ""
        assert "Your ElevenLabs key is already saved" in _screen_text(pilot, "#key-provider-info")

        await click_next(pilot)  # finish
        summary = _screen_text(pilot, "#finish-summary")
        assert "Narration service: OpenAI for now" in summary
        assert "ElevenLabs API key: saved" in summary
        await click_next(pilot)
    # The key went to ElevenLabs only; the active provider was not switched.
    assert ("set", ("elevenlabs", "el-secret")) in service.calls
    assert all(call[0] != "set" or call[1][0] == "elevenlabs" for call in service.calls)
    assert (
        "complete",
        ("marin", Path("/tmp/epub-cache"), Path("/tmp/books")),
    ) in service.calls


@pytest.mark.asyncio
async def test_changing_provider_discards_a_typed_key() -> None:
    service = FakeService()
    async with EPUB2M4BApp(service).run_test() as pilot:
        await go_to_provider_step(pilot)
        field = pilot.app.screen.query_one("#api-key-input", Input)
        field.value = "typed-for-openai"
        pilot.app.screen.query_one("#provider-select", Select).value = "elevenlabs"
        await pilot.pause(0.2)
        assert field.value == ""
        await click_next(pilot)
        await click_next(pilot)
    assert all(call[0] != "set" for call in service.calls)


class KwargService(FakeService):
    """A service whose onboarding accepts provider changes, like the real one."""

    def complete_onboarding(self, voice_id, cache_directory=None, book_directory=None, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("complete", (voice_id, cache_directory, book_directory, kwargs)))


@pytest.mark.asyncio
async def test_a_future_verified_provider_is_offered_and_becomes_the_narration_provider() -> None:
    service = KwargService()
    acme = ProviderOption(
        id="acme",
        name="Acme Voice",
        label="Acme Voice (verified)",
        live_verified=True,
        default_model="acme-1",
        key_url="https://acme.example/keys",
        billing_url="",
        credential_env="ACME_API_KEY",
    )
    service.state = OnboardingState(
        completed=False,
        selected_voice="marin",
        credential_status="unconfigured",
        dependencies=(),
        voices=(Voice("marin", "Marin"),),
        cache_directory=Path("/tmp/epub-cache"),
        book_directory=Path("/tmp/books"),
        providers=(*provider_options(), acme),
    )
    async with EPUB2M4BApp(service).run_test() as pilot:
        await go_to_provider_step(pilot)
        pilot.app.screen.query_one("#provider-select", Select).value = "acme"
        await pilot.pause(0.2)
        await click_next(pilot)
        assert "https://acme.example/keys" in _screen_text(pilot, "#key-provider-info")
        assert pilot.app.screen.query_one("#api-key-input", Input).placeholder == (
            "Paste your Acme Voice API key"
        )
        await click_next(pilot)
        assert "Narration service: Acme Voice" in _screen_text(pilot, "#finish-summary")
        await click_next(pilot)
    assert (
        "complete",
        (
            "marin",
            Path("/tmp/epub-cache"),
            Path("/tmp/books"),
            {"provider": "acme", "model": "acme-1"},
        ),
    ) in service.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "elevenlabs"])
async def test_provider_and_key_steps_fit_an_80_by_24_terminal(provider: str) -> None:
    async with EPUB2M4BApp(FakeService()).run_test(size=(80, 24)) as pilot:
        await go_to_provider_step(pilot)
        pilot.app.screen.query_one("#provider-select", Select).value = provider
        await pilot.pause(0.2)
        for selector in ("#provider-select", "#provider-info", "#next", "#back"):
            _assert_on_screen(pilot, selector)
        await click_next(pilot)
        # The long billing URLs wrap here; the Save button must still be reachable.
        for selector in ("#key-provider-info", "#api-key-input", "#save-key", "#next"):
            _assert_on_screen(pilot, selector)


def _assert_on_screen(pilot: object, selector: str) -> None:
    region = pilot.app.screen.query_one(selector).region  # type: ignore[attr-defined]
    height = pilot.app.size.height  # type: ignore[attr-defined]
    assert region.height > 0 and region.y + region.height <= height, selector


def app_screen_name(pilot: object) -> str:
    return pilot.app.screen.__class__.__name__  # type: ignore[attr-defined]


async def click_next(pilot: object) -> None:
    await pilot.click("#next")  # type: ignore[attr-defined]
    await pilot.pause(0.5)  # type: ignore[attr-defined]
