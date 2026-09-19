from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Button, Input, Select, Static

from epub2m4b.app.onboarding import OnboardingState
from epub2m4b.tui.app import EPUB2M4BApp


class Voice:
    id = "marin"
    display_name = "Marin"


class FakeSettingsService:
    def __init__(
        self,
        credential_status: str = "unconfigured",
        elevenlabs_credential_status: str = "unconfigured",
    ) -> None:
        self.calls: list[tuple[str, object]] = []
        self.credential_status = credential_status
        self.elevenlabs_credential_status = elevenlabs_credential_status

    def onboarding_state(self) -> OnboardingState:
        return OnboardingState(
            True,
            "marin",
            self.credential_status,
            (),
            (Voice(),),
            Path("/tmp/epub-cache"),
            Path("/books"),
            output_directory=Path("/audiobooks"),
            elevenlabs_credential_status=self.elevenlabs_credential_status,
        )

    def set_openai_credential(self, secret: str) -> None:
        self.calls.append(("set_credential", secret))
        self.credential_status = "configured"

    def remove_openai_credential(self) -> None:
        self.calls.append(("remove_credential", None))
        self.credential_status = "unconfigured"

    def set_elevenlabs_credential(self, secret: str) -> None:
        self.calls.append(("set_elevenlabs_credential", secret))
        self.elevenlabs_credential_status = "configured"

    def remove_elevenlabs_credential(self) -> None:
        self.calls.append(("remove_elevenlabs_credential", None))
        self.elevenlabs_credential_status = "unconfigured"

    def force_reonboard(self) -> Path:
        self.calls.append(("force_reonboard", None))
        return Path("/tmp/epub2m4b-reset.json")

    async def test_openai_connection(self, model: str) -> str:
        self.calls.append(("test_openai_connection", model))
        return model

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

    def shutdown(self) -> None:
        pass


@pytest.mark.asyncio
async def test_settings_credential_field_renders_masked_and_unconfigured() -> None:
    service = FakeSettingsService("unconfigured")
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-settings")
        await pilot.pause(0.2)
        screen = app.screen
        assert screen.__class__.__name__ == "SettingsScreen"

        status = screen.query_one("#settings-credential-status", Static)
        assert "No OpenAI key is saved yet" in str(status.renderable)

        key_input = screen.query_one("#settings-credential-input", Input)
        assert key_input.password is True
        assert key_input.value == ""

        remove_button = screen.query_one("#settings-remove-credential", Button)
        assert remove_button.disabled is True

        save_button = screen.query_one("#settings-save-credential", Button)
        assert save_button.disabled is False


@pytest.mark.asyncio
async def test_settings_save_credential_persists_and_updates_status() -> None:
    service = FakeSettingsService("unconfigured")
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-settings")
        await pilot.pause(0.2)
        screen = app.screen

        key_input = screen.query_one("#settings-credential-input", Input)
        key_input.scroll_visible()
        await pilot.pause(0.2)
        key_input.value = "sk-test-secret-key-12345"

        save_button = screen.query_one("#settings-save-credential", Button)
        save_button.scroll_visible()
        await pilot.pause(0.2)
        await pilot.click("#settings-save-credential")
        await pilot.pause(0.2)

        assert ("set_credential", "sk-test-secret-key-12345") in service.calls
        assert key_input.value == ""

        status = screen.query_one("#settings-credential-status", Static)
        assert "An OpenAI key is saved on this computer" in str(status.renderable)

        remove_button = screen.query_one("#settings-remove-credential", Button)
        assert remove_button.disabled is False

        message = screen.query_one("#settings-message", Static)
        assert "saved securely" in str(message.renderable)


@pytest.mark.asyncio
async def test_settings_submit_credential_via_enter() -> None:
    service = FakeSettingsService("unconfigured")
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-settings")
        await pilot.pause(0.2)
        screen = app.screen

        key_input = screen.query_one("#settings-credential-input", Input)
        key_input.scroll_visible()
        await pilot.pause(0.2)
        key_input.value = "sk-submitted-via-enter"
        key_input.focus()
        await pilot.press("enter")
        await pilot.pause(0.2)

        assert ("set_credential", "sk-submitted-via-enter") in service.calls
        assert key_input.value == ""

        status = screen.query_one("#settings-credential-status", Static)
        assert "An OpenAI key is saved on this computer" in str(status.renderable)


@pytest.mark.asyncio
async def test_settings_empty_credential_shows_prompt_without_calling_service() -> None:
    service = FakeSettingsService("unconfigured")
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-settings")
        await pilot.pause(0.2)

        save_button = app.screen.query_one("#settings-save-credential", Button)
        save_button.scroll_visible()
        await pilot.pause(0.2)
        await pilot.click("#settings-save-credential")
        await pilot.pause(0.2)

        assert not any(call[0] == "set_credential" for call in service.calls)
        message = app.screen.query_one("#settings-message", Static)
        assert "Paste or type an OpenAI API key first" in str(message.renderable)


@pytest.mark.asyncio
async def test_settings_remove_credential_deletes_and_updates_status() -> None:
    service = FakeSettingsService("configured")
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-settings")
        await pilot.pause(0.2)
        screen = app.screen

        remove_button = screen.query_one("#settings-remove-credential", Button)
        assert remove_button.disabled is False

        remove_button.scroll_visible()
        await pilot.pause(0.2)
        await pilot.click("#settings-remove-credential")
        await pilot.pause(0.2)

        assert ("remove_credential", None) in service.calls
        assert remove_button.disabled is True

        status = screen.query_one("#settings-credential-status", Static)
        assert "No OpenAI key is saved yet" in str(status.renderable)

        message = screen.query_one("#settings-message", Static)
        assert "removed" in str(message.renderable)


@pytest.mark.asyncio
async def test_save_all_settings_also_saves_pending_credential() -> None:
    service = FakeSettingsService("unconfigured")
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-settings")
        await pilot.pause(0.2)
        screen = app.screen

        key_input = screen.query_one("#settings-credential-input", Input)
        key_input.value = "sk-saved-with-all-settings"

        await pilot.click("#save-settings")
        await pilot.pause(0.2)

        assert ("set_credential", "sk-saved-with-all-settings") in service.calls
        assert key_input.value == ""
        assert any(call[0] == "complete" for call in service.calls)

        status = screen.query_one("#settings-credential-status", Static)
        assert "An OpenAI key is saved on this computer" in str(status.renderable)


@pytest.mark.asyncio
async def test_settings_displays_environment_variable_status() -> None:
    service = FakeSettingsService("environment")
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-settings")
        await pilot.pause(0.2)
        screen = app.screen

        status = screen.query_one("#settings-credential-status", Static)
        assert "OPENAI_API_KEY environment variable" in str(status.renderable)
        assert screen.query_one("#settings-remove-credential", Button).disabled is True


@pytest.mark.asyncio
async def test_force_reonboard_requires_reset_and_returns_to_onboarding() -> None:
    service = FakeSettingsService("configured")
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-settings")
        await pilot.pause(0.2)
        reset = app.screen.query_one("#settings-force-reonboard", Button)
        reset.scroll_visible()
        await pilot.pause(0.2)
        await pilot.click("#settings-force-reonboard")
        await pilot.pause(0.2)

        confirmation = app.screen.query_one("#force-reonboard-input", Input)
        confirmation.value = "RESET"
        await pilot.click("#force-reonboard-confirm")
        await pilot.pause(0.3)

        assert ("force_reonboard", None) in service.calls
        assert app.screen.__class__.__name__ == "OnboardingScreen"


@pytest.mark.asyncio
async def test_openai_connection_button_checks_saved_key_and_model() -> None:
    service = FakeSettingsService("configured")
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-settings")
        await pilot.pause(0.2)
        button = app.screen.query_one("#settings-test-openai", Button)
        button.scroll_visible()
        await pilot.pause(0.2)
        await pilot.click("#settings-test-openai")
        await pilot.pause(0.3)

        assert ("test_openai_connection", "gpt-4o-mini-tts") in service.calls
        message = app.screen.query_one("#settings-message", Static)
        assert "OpenAI is reachable" in str(message.renderable)


@pytest.mark.asyncio
async def test_settings_elevenlabs_credential_renders_and_saves() -> None:
    service = FakeSettingsService("unconfigured", elevenlabs_credential_status="unconfigured")
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-settings")
        await pilot.pause(0.2)
        screen = app.screen

        status = screen.query_one("#settings-elevenlabs-credential-status", Static)
        assert "No ElevenLabs key is saved yet" in str(status.renderable)

        key_input = screen.query_one("#settings-elevenlabs-credential-input", Input)
        assert key_input.password is True

        key_input.scroll_visible()
        await pilot.pause(0.2)
        key_input.value = "xi-test-secret-key-12345"

        save_btn = screen.query_one("#settings-save-elevenlabs-credential", Button)
        save_btn.scroll_visible()
        await pilot.pause(0.2)
        await pilot.click("#settings-save-elevenlabs-credential")
        await pilot.pause(0.2)

        assert ("set_elevenlabs_credential", "xi-test-secret-key-12345") in service.calls
        assert key_input.value == ""
        assert "An ElevenLabs key is saved on this computer" in str(status.renderable)


@pytest.mark.asyncio
async def test_settings_remove_elevenlabs_credential() -> None:
    service = FakeSettingsService("unconfigured", elevenlabs_credential_status="configured")
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-settings")
        await pilot.pause(0.2)
        screen = app.screen

        remove_btn = screen.query_one("#settings-remove-elevenlabs-credential", Button)
        assert remove_btn.disabled is False
        remove_btn.scroll_visible()
        await pilot.pause(0.2)
        await pilot.click("#settings-remove-elevenlabs-credential")
        await pilot.pause(0.2)

        assert ("remove_elevenlabs_credential", None) in service.calls
        assert remove_btn.disabled is True
        status = screen.query_one("#settings-elevenlabs-credential-status", Static)
        assert "No ElevenLabs key is saved yet" in str(status.renderable)


@pytest.mark.asyncio
async def test_settings_provider_switch_updates_models() -> None:
    service = FakeSettingsService("unconfigured")
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-settings")
        await pilot.pause(0.2)
        screen = app.screen

        provider_select = screen.query_one("#settings-provider", Select)
        model_select = screen.query_one("#settings-model", Select)

        # Switch to ElevenLabs
        provider_select.value = "elevenlabs"
        await pilot.pause(0.2)
        assert model_select.value == "eleven_multilingual_v2"

        # Switch back to OpenAI
        provider_select.value = "openai"
        await pilot.pause(0.2)
        assert model_select.value == "gpt-4o-mini-tts"


@pytest.mark.asyncio
async def test_settings_save_refuses_untested_elevenlabs_provider() -> None:
    service = FakeSettingsService("unconfigured")
    app = EPUB2M4BApp(service)
    async with app.run_test() as pilot:
        await pilot.click("#nav-settings")
        await pilot.pause(0.2)
        screen = app.screen

        provider_select = screen.query_one("#settings-provider", Select)
        provider_select.value = "elevenlabs"
        await pilot.pause(0.2)

        save_btn = screen.query_one("#save-settings", Button)
        save_btn.scroll_visible()
        await pilot.pause(0.2)
        await pilot.click("#save-settings")
        await pilot.pause(0.2)

        message = screen.query_one("#settings-message", Static)
        assert "UNTESTED" in str(message.renderable)
        assert not any(call[0] == "complete" for call in service.calls)
