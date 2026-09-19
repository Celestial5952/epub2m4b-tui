"""Direct, non-wizard settings for storage, narration, and spending limits."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Select, Static, TextArea

from epub2m4b.app.service import ApplicationService

from .directory_picker import DirectoryPickerScreen
from .force_reonboard import ForceReonboardScreen
from .navigation import NavigationBar

_OPENAI_MODELS = (
    ("gpt-4o-mini-tts", "gpt-4o-mini-tts"),
)

_PROVIDERS = (
    ("OpenAI (verified)", "openai"),
    ("ElevenLabs — UNTESTED live, not available yet", "elevenlabs"),
)

_CREDENTIAL_LABELS = {
    "configured": "An OpenAI key is saved on this computer.",
    "environment": "Using the OPENAI_API_KEY environment variable.",
    "unconfigured": "No OpenAI key is saved yet.",
    "unavailable": "Secure credential storage is unavailable on this computer.",
}


def _voice_id(entry: Any) -> str:
    return str(getattr(entry, "id", ""))


def _voice_name(entry: Any) -> str:
    return str(getattr(entry, "display_name", _voice_id(entry)))


class SettingsScreen(Screen[None]):
    """Edit common settings without replaying first-run onboarding."""

    def __init__(self, service: ApplicationService, state: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.service = service
        self.state = state
        self._voice_ids = tuple(_voice_id(entry) for entry in state.voices)
        self.selected_voice = str(state.selected_voice)

    def compose(self) -> ComposeResult:
        voice_options = tuple(
            (_voice_name(entry), _voice_id(entry)) for entry in self.state.voices
        )
        credential_text = _CREDENTIAL_LABELS.get(
            str(getattr(self.state, "credential_status", "unconfigured")),
            "No OpenAI key is saved yet.",
        )
        yield Header(show_clock=False)
        with Container(id="settings-screen"):
            with Container(id="settings-nav"):
                yield NavigationBar("settings")
            with VerticalScroll(id="settings"):
                with Container(id="settings-inner"):
                    yield Static("Settings", id="settings-title")
                yield Static("Book library", classes="section-title")
                yield Static(
                    "Choose the folder containing your EPUB books. It will be rescanned "
                    "when you return to Library."
                )
                with Horizontal(classes="directory-row"):
                    yield Input(
                        value=str(self.state.book_directory or ""),
                        placeholder="Choose your book folder",
                        id="settings-book-directory",
                    )
                    yield Button(
                        "Choose folder…", id="settings-browse-books", variant="primary"
                    )
                yield Static("Temporary narration audio", classes="section-title")
                yield Static(
                    "Stores validated chapter audio chunks locally. Preserved across sessions "
                    "so completed pieces are never regenerated."
                )
                with Horizontal(classes="directory-row"):
                    yield Input(
                        value=str(self.state.cache_directory or ""),
                        placeholder="Choose a cache folder",
                        id="settings-cache-directory",
                    )
                    yield Button("Choose folder…", id="settings-browse-cache")
                yield Static("Finished audiobooks", classes="section-title")
                yield Static(
                    "Choose where your completed M4B audiobooks are saved. Audiobooks are "
                    "encoded with AAC audio, embedded cover art, and chapter markers."
                )
                with Horizontal(classes="directory-row"):
                    yield Input(
                        value=str(getattr(self.state, "output_directory", None) or ""),
                        placeholder="Choose an output folder",
                        id="settings-output-directory",
                    )
                    yield Button("Choose folder…", id="settings-browse-output")
                yield Static("Narration voice", classes="section-title")
                yield Select(
                    voice_options,
                    value=(
                        self.selected_voice
                        if self.selected_voice in self._voice_ids
                        else Select.BLANK
                    ),
                    allow_blank=not bool(voice_options),
                    id="settings-voice",
                )
                yield Static("Narration provider", classes="section-title")
                yield Static(
                    "ElevenLabs support is still being verified and is marked "
                    "UNTESTED live, so it cannot be selected yet."
                )
                yield Select(
                    _PROVIDERS,
                    value=str(getattr(self.state, "provider", "openai")),
                    id="settings-provider",
                )
                yield Static("Narration model", classes="section-title")
                yield Select(
                    _OPENAI_MODELS,
                    value=(
                        str(getattr(self.state, "model", "gpt-4o-mini-tts"))
                        if str(getattr(self.state, "model", "gpt-4o-mini-tts"))
                        in {value for _, value in _OPENAI_MODELS}
                        else "gpt-4o-mini-tts"
                    ),
                    id="settings-model",
                )
                yield Static("Reading speed", classes="section-title")
                yield Static(
                    "Narration speed multiplier (default: 1.0). For example, 1.25 reads 25% faster."
                )
                yield Input(
                    value=str(getattr(self.state, "speed", 1.0)),
                    placeholder="1",
                    id="settings-speed",
                )
                yield Static("Narration style instructions", classes="section-title")
                yield TextArea(
                    text=str(getattr(self.state, "instructions", "")),
                    id="settings-instructions",
                )
                yield Static("Spending limit", classes="section-title")
                yield Static(
                    "Safety budget threshold in US dollars. The app refuses any narration "
                    "whose estimated cost exceeds this limit (default: $25.00)."
                )
                yield Input(
                    value=str(getattr(self.state, "maximum_estimated_cost_usd", 25.0)),
                    placeholder="25",
                    id="settings-cost-cap",
                )
                yield Static("OpenAI credential", classes="section-title")
                yield Static(
                    "Narration requires an OpenAI API key. Keys are saved securely "
                    "in your computer's system keyring."
                )
                yield Static(credential_text, id="settings-credential-status")
                with Horizontal(classes="directory-row"):
                    yield Input(
                        placeholder="Paste your OpenAI API key",
                        password=True,
                        id="settings-credential-input",
                    )
                    yield Button("Save key", id="settings-save-credential", variant="primary")
                yield Button(
                    "Test OpenAI connection",
                    id="settings-test-openai",
                    variant="primary",
                )
                yield Static(
                    "Checks the saved key and gpt-4o-mini-tts access without creating "
                    "audio or using TTS credits."
                )
                yield Button(
                    "Remove saved OpenAI key",
                    id="settings-remove-credential",
                    variant="error",
                    disabled=str(getattr(self.state, "credential_status", ""))
                    != "configured",
                )
                yield Static("Start over", classes="section-title")
                yield Static(
                    "Export your non-secret settings and activity history, remove saved app "
                    "state and keys, then return to first-time setup."
                )
                yield Button(
                    "Force re-onboard…", id="settings-force-reonboard", variant="error"
                )
            with Horizontal(id="settings-footer"):
                yield Static("", id="settings-message")
                yield Button("Save settings", id="save-settings", variant="success")
        yield Footer()

    def _browse(self, selector: str) -> None:
        field = self.query_one(selector, Input)
        initial = Path(field.value) if field.value.strip() else None

        def selected(path: Path | None) -> None:
            if path is not None:
                field.value = str(path)

        self.app.push_screen(DirectoryPickerScreen(initial), selected)

    def _navigate(self, destination: str) -> None:
        method = getattr(self.app, f"show_{destination}", None)
        if callable(method):
            method()

    def on_select_changed(self, event: Select.Changed[str]) -> None:
        if event.select.id == "settings-voice" and event.value is not Select.BLANK:
            self.selected_voice = str(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "settings-credential-input":
            self._save_credential()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "nav-library":
            self._navigate("library")
        elif button_id == "nav-jobs":
            self._navigate("jobs")
        elif button_id == "nav-voices":
            self._navigate("voices")
        elif button_id == "nav-logs":
            self._navigate("logs")
        elif button_id == "settings-browse-books":
            self._browse("#settings-book-directory")
        elif button_id == "settings-browse-cache":
            self._browse("#settings-cache-directory")
        elif button_id == "settings-browse-output":
            self._browse("#settings-output-directory")
        elif button_id == "settings-save-credential":
            self._save_credential()
        elif button_id == "settings-test-openai":
            await self._test_openai_connection()
        elif button_id == "settings-remove-credential":
            self._remove_credential()
        elif button_id == "settings-force-reonboard":
            self.app.push_screen(ForceReonboardScreen(), self._force_reonboard)
        elif button_id == "save-settings":
            self._save()

    def _save_credential(self) -> bool:
        message = self.query_one("#settings-message", Static)
        field = self.query_one("#settings-credential-input", Input)
        secret = field.value.strip()
        if not secret:
            message.update("Paste or type an OpenAI API key first.")
            return False
        try:
            self.service.set_openai_credential(secret)
            self.query_one("#settings-credential-status", Static).update(
                _CREDENTIAL_LABELS["configured"]
            )
            self.query_one("#settings-remove-credential", Button).disabled = False
            message.update("OpenAI key saved securely to system keyring.")
        except Exception:
            message.update("The key could not be saved to secure storage. Try again.")
            return False
        finally:
            field.value = ""
        return True

    def _remove_credential(self) -> None:
        message = self.query_one("#settings-message", Static)
        try:
            self.service.remove_openai_credential()
            self.query_one("#settings-credential-status", Static).update(
                _CREDENTIAL_LABELS["unconfigured"]
            )
            self.query_one("#settings-remove-credential", Button).disabled = True
            message.update("Saved OpenAI key removed.")
        except Exception:
            message.update("The saved key could not be removed. Try again.")
            return

    async def _test_openai_connection(self) -> None:
        message = self.query_one("#settings-message", Static)
        field = self.query_one("#settings-credential-input", Input)
        if field.value.strip() and not self._save_credential():
            return
        button = self.query_one("#settings-test-openai", Button)
        button.disabled = True
        message.update("Testing OpenAI connection and model access…")
        try:
            model = str(self.query_one("#settings-model", Select).value)
            verified = await self.service.test_openai_connection(model)
        except Exception as exc:
            detail = str(exc).strip() or "unknown connection error"
            message.update(f"OpenAI test failed: {detail}")
            return
        finally:
            button.disabled = False
        message.update(f"OpenAI is reachable. The saved key can access {verified}.")

    def _save(self) -> None:
        message = self.query_one("#settings-message", Static)
        books = self.query_one("#settings-book-directory", Input).value.strip()
        cache = self.query_one("#settings-cache-directory", Input).value.strip()
        output = self.query_one("#settings-output-directory", Input).value.strip()
        speed_text = self.query_one("#settings-speed", Input).value.strip()
        cap_text = self.query_one("#settings-cost-cap", Input).value.strip()
        instructions = self.query_one("#settings-instructions", TextArea).text
        provider = str(self.query_one("#settings-provider", Select).value)
        model = str(self.query_one("#settings-model", Select).value)
        key_input = self.query_one("#settings-credential-input", Input)
        secret = key_input.value.strip()
        if not self.selected_voice:
            message.update("Choose a voice before saving.")
            return
        if provider != "openai":
            message.update(
                "ElevenLabs is marked UNTESTED live and cannot be selected yet. "
                "Keep OpenAI chosen."
            )
            return
        try:
            speed = float(speed_text) if speed_text else None
        except ValueError:
            message.update("Reading speed must be a number, like 1 or 1.1.")
            return
        try:
            cap = float(cap_text) if cap_text else None
        except ValueError:
            message.update("The spending limit must be a number, like 25.")
            return
        if secret:
            try:
                self.service.set_openai_credential(secret)
                self.query_one("#settings-credential-status", Static).update(
                    _CREDENTIAL_LABELS["configured"]
                )
                self.query_one("#settings-remove-credential", Button).disabled = False
            except Exception:
                message.update("The OpenAI key could not be saved. Try again.")
                return
            finally:
                key_input.value = ""
        try:
            self.service.complete_onboarding(
                self.selected_voice,
                Path(cache) if cache else None,
                Path(books) if books else None,
                output_directory=Path(output) if output else None,
                provider=provider,
                model=model,
                speed=speed,
                instructions=instructions,
                maximum_estimated_cost_usd=cap,
            )
        except Exception:
            message.update(
                "Those settings could not be saved. Check the folders and numbers, "
                "then try again."
            )
            return
        message.update("Settings saved. Return to Library to see your books.")

    def _force_reonboard(self, confirmed: bool) -> None:
        if not confirmed:
            return
        message = self.query_one("#settings-message", Static)
        try:
            export_path = self.service.force_reonboard()
        except Exception as exc:
            detail = str(exc).strip() or "unknown local error"
            message.update(f"Could not reset the application: {detail}")
            self.app.notify(f"Reset failed: {detail}", severity="error")
            return
        self.app.show_onboarding()  # type: ignore[attr-defined]
        self.app.notify(f"Reset complete. Export saved to {export_path}")


__all__ = ["SettingsScreen"]
