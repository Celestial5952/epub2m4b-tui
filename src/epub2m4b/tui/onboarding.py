"""First-run onboarding widgets.

The screen deliberately knows only the application service protocol.  It never
opens audio files, resolves executables, or handles credentials beyond passing a
masked input value to that service.
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Select, Static

from epub2m4b.app.service import ApplicationService

from .directory_picker import DirectoryPickerScreen


def _voice_id(entry: Any) -> str:
    return str(getattr(entry, "id", ""))


def _voice_name(entry: Any) -> str:
    return str(getattr(entry, "display_name", _voice_id(entry)))


class OnboardingScreen(Screen[None]):
    """Keyboard-navigable, skippable onboarding wizard."""

    BINDINGS = [("left", "back", "Back"), ("right", "next", "Next"), ("s", "skip", "Skip")]

    def __init__(
        self,
        service: ApplicationService,
        state: Any,
        *,
        initial_step: int = 0,
        settings_mode: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.service = service
        self.state = state
        self.step = initial_step
        self.settings_mode = settings_mode
        self.selected_voice = str(state.selected_voice)
        self._voice_ids = tuple(_voice_id(entry) for entry in state.voices)
        self.cache_directory = str(state.cache_directory or "")
        self.book_directory = str(state.book_directory or "")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="onboarding"):
            yield Static("Welcome", id="step-title")
            yield Static("", id="message")
            with Container(id="welcome-step", classes="step"):
                yield Static(
                    "Turn your EPUB books into audiobooks with a few guided choices.\n\n"
                    "You can use the mouse, and you do not need to know any terminal commands. "
                    "Your book is read on this computer. Narration uses an account you control."
                )
            with Container(id="system-step", classes="step"):
                yield Static("Checking the audio tools on this computer", classes="section-title")
                yield Static(self._dependency_text(), id="dependency-status")
            with Container(id="storage-step", classes="step"):
                yield Static(
                    "Where should temporary narration audio be kept?\n"
                    "The suggested location is fine for most people."
                )
                with Horizontal(classes="directory-row"):
                    yield Input(
                        value=self.cache_directory,
                        placeholder="Choose a cache folder",
                        id="cache-directory",
                    )
                    yield Button("Choose folder…", id="browse-cache")
                yield Static("Now choose the folder where you keep your EPUB books.")
                with Horizontal(classes="directory-row"):
                    yield Input(
                        value=self.book_directory,
                        placeholder="Choose your book folder",
                        id="book-directory",
                    )
                    yield Button("Choose folder…", id="browse-books", variant="primary")
                yield Static(
                    "Nothing in your book folder will be changed. We only look for EPUB files."
                )
            with Container(id="voice-step", classes="step"):
                yield Static("Choose a bundled voice. These auditions work offline.")
                yield Select(
                    tuple((_voice_name(entry), _voice_id(entry)) for entry in self.state.voices),
                    value=self.selected_voice
                    if self.selected_voice in self._voice_ids
                    else Select.BLANK,
                    id="voice-select",
                    allow_blank=False,
                )
                with Vertical(id="voice-actions"):
                    for entry in self.state.voices:
                        voice_id = _voice_id(entry)
                        yield Horizontal(
                            Label(_voice_name(entry)),
                            Button("Play", id=f"play-{voice_id}"),
                            Button("Stop", id=f"stop-{voice_id}"),
                            classes="voice-row",
                        )
            with Container(id="key-step", classes="step"):
                yield Static(
                    "This step is optional. An API key is only needed when you are ready to "
                    "create narration. Before anything can cost money, the app shows an "
                    "estimate and asks you to confirm."
                )
                yield Input(
                    placeholder="Paste your OpenAI API key", password=True, id="api-key-input"
                )
                yield Button("Save key", id="save-key")
            with Container(id="finish-step", classes="step"):
                yield Static("Everything is ready.", classes="section-title")
                yield Static("", id="finish-summary")
                yield Static(
                    "Next, choose a book from your library. Nothing is charged just for "
                    "opening or checking a book."
                )
            with Horizontal(id="navigation"):
                yield Button("Back", id="back", disabled=True)
                yield Button("Next", id="next", variant="primary")
                yield Button("Cancel" if self.settings_mode else "Skip setup", id="skip")
        yield Footer()

    def on_mount(self) -> None:
        self._show_step()

    def _dependency_text(self) -> str:
        try:
            dependencies = self.state.dependencies
            entries = getattr(dependencies, "entries", None)
            if entries is not None:
                labels = {
                    "ffmpeg": "Audiobook builder",
                    "ffprobe": "Audio checker",
                    "ffplay": "Voice preview player",
                }
                lines = []
                for entry in entries:
                    name = str(getattr(entry, "name", "audio tool"))
                    label = labels.get(name, "Audio tool")
                    available = bool(getattr(entry, "available", False))
                    required = bool(getattr(entry, "required", True))
                    if available:
                        lines.append(f"✓ {label}: ready")
                    elif required:
                        lines.append(f"! {label}: needs attention")
                    else:
                        lines.append(f"– {label}: optional and not installed")
                return "\n".join(lines) or "Audio-tool details are unavailable."
            if isinstance(dependencies, (tuple, list)):
                return (
                    "\n".join(str(item) for item in dependencies)
                    or "Audio-tool details are unavailable."
                )
            return str(dependencies)
        except Exception:
            return "We could not check the audio tools. You can continue and try again later."

    def _show_step(self) -> None:
        titles = (
            "Welcome",
            "System check",
            "Storage and books",
            "Choose a voice",
            "Optional API setup",
            "Finish",
        )
        for index, name in enumerate(
            ("welcome", "system", "storage", "voice", "key", "finish")
        ):
            self.query_one(f"#{name}-step").styles.display = (
                "block" if index == self.step else "none"
            )
        self.query_one("#step-title", Static).update(
            f"{titles[self.step]}  ·  Step {self.step + 1} of {len(titles)}"
        )
        self.query_one("#back", Button).disabled = self.step == 0
        self.query_one("#next", Button).label = "Finish" if self.step == 5 else "Next"
        self.query_one("#message", Static).update("")
        if self.step == 5:
            cache = self.query_one("#cache-directory", Input).value.strip() or "Not selected"
            books = self.query_one("#book-directory", Input).value.strip() or "Not selected"
            voice_name = next(
                (
                    _voice_name(entry)
                    for entry in self.state.voices
                    if _voice_id(entry) == self.selected_voice
                ),
                self.selected_voice,
            )
            self.query_one("#finish-summary", Static).update(
                f"Voice: {voice_name}\n"
                f"Book folder: {books}\n"
                f"Temporary audio: {cache}"
            )

    def _set_error(self) -> None:
        self.query_one("#message", Static).update(
            "That action could not be completed. Please try again."
        )

    def _leave(self) -> None:
        self._clear_key()
        app = self.app
        if self.settings_mode:
            app.pop_screen()
            screen = app.screen
            refresh = getattr(screen, "refresh_library", None)
            if callable(refresh):
                app.run_worker(refresh())
            return
        if hasattr(app, "show_home"):
            app.show_home()

    def _clear_key(self) -> None:
        with suppress(Exception):
            self.query_one("#api-key-input", Input).value = ""

    def _save_key_and_clear(self) -> bool:
        field = self.query_one("#api-key-input", Input)
        secret = field.value
        if not secret.strip():
            field.value = ""
            return True
        try:
            self.service.set_openai_credential(secret)
        except Exception:
            self._set_error()
            return False
        finally:
            field.value = ""
        return True

    def _advance(self) -> None:
        if self.step == 4 and not self._save_key_and_clear():
            return
        if self.step < 5:
            self.step += 1
            self._show_step()
            return
        try:
            cache_directory = self.query_one("#cache-directory", Input).value.strip()
            book_directory = self.query_one("#book-directory", Input).value.strip()
            self.service.complete_onboarding(
                self.selected_voice,
                Path(cache_directory) if cache_directory else None,
                Path(book_directory) if book_directory else None,
            )
        except Exception:
            self._set_error()
            return
        self._leave()

    def action_next(self) -> None:
        self._advance()

    def action_back(self) -> None:
        if self.step > 0:
            if self.step == 4:
                self._clear_key()
            self.step -= 1
            self._show_step()

    def action_skip(self) -> None:
        self._clear_key()
        if self.settings_mode:
            self.app.pop_screen()
            return
        try:
            self.service.skip_onboarding()
        except Exception:
            self._set_error()
            return
        self._leave()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "next":
            self._advance()
        elif button_id == "back":
            self.action_back()
        elif button_id == "skip":
            self.action_skip()
        elif button_id == "save-key":
            self._save_key_and_clear()
        elif button_id == "browse-cache":
            self._browse_directory("#cache-directory")
        elif button_id == "browse-books":
            self._browse_directory("#book-directory")
        elif button_id.startswith("play-"):
            try:
                self.service.play_voice_preview(button_id[5:])
            except Exception:
                self._set_error()
        elif button_id.startswith("stop-"):
            try:
                self.service.stop_voice_preview()
            except Exception:
                self._set_error()

    def _browse_directory(self, input_selector: str) -> None:
        field = self.query_one(input_selector, Input)
        initial = Path(field.value) if field.value.strip() else None

        def selected(path: Path | None) -> None:
            if path is not None:
                field.value = str(path)

        self.app.push_screen(DirectoryPickerScreen(initial), selected)

    def on_select_changed(self, event: Select.Changed[str]) -> None:
        if event.value is not Select.BLANK:
            self.selected_voice = str(event.value)


__all__ = ["OnboardingScreen"]
