"""Reusable keyboard-friendly directory picker for the Textual UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Static


class DirectoryPickerScreen(ModalScreen[Path | None]):
    """Browse from the filesystem root and return one selected directory."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, initial: Path | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.selected = self._initial_directory(initial)

    @staticmethod
    def _initial_directory(initial: Path | None) -> Path:
        if initial is not None:
            try:
                candidate = Path(initial).expanduser().resolve(strict=True)
                if candidate.is_dir():
                    return candidate
            except (OSError, RuntimeError):
                pass
        return Path.home()

    def compose(self) -> ComposeResult:
        with Container(id="directory-picker"):
            yield Static("Choose a folder", id="directory-picker-title")
            yield Static(str(self.selected), id="selected-directory")
            yield DirectoryTree(Path("/"), id="directory-tree")
            with Horizontal(id="directory-picker-actions"):
                yield Button("Use selected folder", id="choose-directory", variant="primary")
                yield Button("Cancel", id="cancel-directory")

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        self.selected = event.path
        self.query_one("#selected-directory", Static).update(str(event.path))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "choose-directory":
            self.dismiss(self.selected)
        elif event.button.id == "cancel-directory":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = ["DirectoryPickerScreen"]
