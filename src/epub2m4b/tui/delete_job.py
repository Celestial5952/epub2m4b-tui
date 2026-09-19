"""Confirmation dialog for deleting one local job record."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class DeleteJobScreen(ModalScreen[bool]):
    """Confirm deletion without touching cached narration or finished books."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title

    def compose(self) -> ComposeResult:
        with Container(id="delete-job-dialog"):
            yield Static("Delete old job?", id="delete-job-heading")
            yield Static(
                f"Delete the saved job record for “{self.title}”? Cached narration and "
                "finished M4B files will be preserved."
            )
            with Horizontal(id="delete-job-actions"):
                yield Button("Keep job", id="delete-job-cancel")
                yield Button("Delete job", id="delete-job-confirm", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "delete-job-confirm":
            self.dismiss(True)
        elif event.button.id == "delete-job-cancel":
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


__all__ = ["DeleteJobScreen"]
