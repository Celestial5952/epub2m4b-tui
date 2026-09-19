"""Explicit confirmation for permanently resetting local app state."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


class ForceReonboardScreen(ModalScreen[bool]):
    """Require a typed confirmation before deleting app-owned state."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Container(id="force-reonboard-dialog"):
            yield Static("Force re-onboard", id="force-reonboard-heading")
            yield Static(
                "This exports your non-secret settings and redacted activity log to a JSON "
                "file in your home folder, then removes saved API keys, app settings, jobs, "
                "and temporary narration cache. Your EPUBs and finished M4B files stay put."
            )
            yield Static("Type RESET to continue.", id="force-reonboard-instruction")
            yield Input(placeholder="RESET", id="force-reonboard-input")
            with Horizontal(id="force-reonboard-actions"):
                yield Button("Cancel", id="force-reonboard-cancel")
                yield Button("Export and reset", id="force-reonboard-confirm", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "force-reonboard-cancel":
            self.dismiss(False)
        elif event.button.id == "force-reonboard-confirm":
            if self.query_one("#force-reonboard-input", Input).value == "RESET":
                self.dismiss(True)
            else:
                self.query_one("#force-reonboard-instruction", Static).update(
                    "Type RESET exactly to continue."
                )

    def action_cancel(self) -> None:
        self.dismiss(False)


__all__ = ["ForceReonboardScreen"]
