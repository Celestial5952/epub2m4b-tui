"""Voice auditions screen for comparing and selecting bundled narration voices."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from epub2m4b.app.service import ApplicationService

from .navigation import NavigationBar


def _voice_id(entry: Any) -> str:
    return str(getattr(entry, "id", ""))


def _voice_name(entry: Any) -> str:
    return str(getattr(entry, "display_name", _voice_id(entry)))


class VoiceCard(Container):
    """One card displaying a bundled voice with play, stop, and select controls."""

    def __init__(self, entry: Any, *, is_default: bool = False) -> None:
        classes = "voice-card default-voice" if is_default else "voice-card"
        super().__init__(classes=classes)
        self.entry = entry
        self.voice_id = _voice_id(entry)
        self.voice_name = _voice_name(entry)
        self.is_default = is_default

    def compose(self) -> ComposeResult:
        badge = "  [Default Voice]" if self.is_default else ""
        duration = getattr(self.entry, "duration_seconds", None)
        duration_str = (
            f" · Duration: {duration:.1f}s"
            if isinstance(duration, (int, float)) and duration > 0
            else ""
        )
        size = getattr(self.entry, "size_bytes", None)
        size_str = (
            f" · {size / 1024:.1f} KB"
            if isinstance(size, (int, float)) and size > 0
            else ""
        )
        with Container(classes="voice-card-header"):
            yield Static(
                f"{self.voice_name}{badge}",
                classes="voice-card-title",
                id=f"voice-title-{self.voice_id}",
            )
            yield Static(
                f"Voice ID: {self.voice_id}{duration_str}{size_str} · Opus audio · Offline preview",
                classes="voice-card-info",
            )
        with Horizontal(classes="voice-card-actions"):
            yield Button("Play audition", id=f"play-{self.voice_id}", variant="primary")
            yield Button("Stop", id=f"stop-{self.voice_id}")
            yield Button(
                "Default voice" if self.is_default else "Set as default",
                id=f"select-{self.voice_id}",
                variant="success",
                disabled=self.is_default,
            )


class VoicesScreen(Screen[None]):
    """Audition auto-generated bundled voices offline and select the default voice."""

    def __init__(
        self,
        service: ApplicationService,
        state: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.service = service
        self.state = state
        if self.state is None:
            with suppress(Exception):
                self.state = self.service.onboarding_state()
        self.selected_voice = (
            str(getattr(self.state, "selected_voice", "")) if self.state else ""
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="voices-screen"):
            yield NavigationBar("voices")
            with Horizontal(id="voices-heading"):
                yield Static("Voice auditions", id="voices-title")
                yield Button("Stop playback", id="stop-all")
            yield Static(
                "Listen to auto-generated bundled voices offline without using API credits. "
                "Compare voices and choose your default for audiobook narration.\n"
                'Audition quote: "At dawn, the old city stirred—quietly at first, '
                'then all at once—as a new adventure began."',
                id="voices-help",
            )
            yield Static("", id="voices-status")
            with VerticalScroll(id="voices-list"):
                if self.state and getattr(self.state, "voices", None):
                    for entry in self.state.voices:
                        yield VoiceCard(
                            entry,
                            is_default=_voice_id(entry) == self.selected_voice,
                        )
                else:
                    yield Static("No voice samples are available.", id="no-voices")
        yield Footer()

    def _status(self, message: str) -> None:
        self.query_one("#voices-status", Static).update(message)

    def _play(self, voice_id: str) -> None:
        try:
            self.service.play_voice_preview(voice_id)
            name = next(
                (
                    _voice_name(entry)
                    for entry in (getattr(self.state, "voices", ()) or ())
                    if _voice_id(entry) == voice_id
                ),
                voice_id,
            )
            self._status(f"Playing audition for {name}…")
        except Exception:
            self._status("Could not play voice preview. Check that audio tools are working.")

    def _stop(self) -> None:
        try:
            self.service.stop_voice_preview()
            self._status("Playback stopped.")
        except Exception:
            self._status("Could not stop voice preview.")

    async def _select_default(self, voice_id: str) -> None:
        if not self.state:
            try:
                self.state = self.service.onboarding_state()
            except Exception:
                self._status("Could not load current settings.")
                return
        try:
            self.service.complete_onboarding(
                voice_id,
                getattr(self.state, "cache_directory", None),
                getattr(self.state, "book_directory", None),
                output_directory=getattr(self.state, "output_directory", None),
                provider=getattr(self.state, "provider", "openai"),
                model=getattr(self.state, "model", "gpt-4o-mini-tts"),
                speed=getattr(self.state, "speed", 1.0),
                instructions=getattr(self.state, "instructions", ""),
                maximum_estimated_cost_usd=getattr(self.state, "maximum_estimated_cost_usd", 25.0),
            )
            self.selected_voice = voice_id
            with suppress(Exception):
                self.state = self.service.onboarding_state()
            await self._refresh_cards()
            name = next(
                (
                    _voice_name(entry)
                    for entry in (getattr(self.state, "voices", ()) or ())
                    if _voice_id(entry) == voice_id
                ),
                voice_id,
            )
            self._status(f"✓ {name} set as default narration voice.")
        except Exception:
            self._status("Could not update default voice setting. Please try again.")

    async def _refresh_cards(self) -> None:
        voices_list = self.query_one("#voices-list", VerticalScroll)
        await voices_list.remove_children()
        if self.state and getattr(self.state, "voices", None):
            for entry in self.state.voices:
                await voices_list.mount(
                    VoiceCard(
                        entry,
                        is_default=_voice_id(entry) == self.selected_voice,
                    )
                )

    def on_unmount(self) -> None:
        with suppress(Exception):
            self.service.stop_voice_preview()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "nav-library":
            self.app.show_library()  # type: ignore[attr-defined]
        elif button_id == "nav-jobs":
            self.app.show_jobs()  # type: ignore[attr-defined]
        elif button_id == "nav-settings":
            self.app.show_settings()  # type: ignore[attr-defined]
        elif button_id == "nav-logs":
            self.app.show_logs()  # type: ignore[attr-defined]
        elif button_id == "stop-all":
            self._stop()
        elif button_id.startswith("play-"):
            self._play(button_id.removeprefix("play-"))
        elif button_id.startswith("stop-"):
            self._stop()
        elif button_id.startswith("select-"):
            await self._select_default(button_id.removeprefix("select-"))


__all__ = ["VoiceCard", "VoicesScreen"]
