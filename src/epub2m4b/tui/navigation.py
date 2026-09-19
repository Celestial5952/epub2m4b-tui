"""Persistent, mouse-friendly application navigation."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button


class NavigationBar(Horizontal):
    """Top-level destinations that remain consistent across the application."""

    def __init__(self, active: str, **kwargs: object) -> None:
        super().__init__(id="app-navigation", **kwargs)
        self.active = active

    def compose(self) -> ComposeResult:
        yield Button("Library", id="nav-library", disabled=self.active == "library")
        yield Button("Jobs", id="nav-jobs", disabled=self.active == "jobs")
        yield Button("Voices", id="nav-voices", disabled=self.active == "voices")
        yield Button("Settings", id="nav-settings", disabled=self.active == "settings")
        yield Button("Logs", id="nav-logs", disabled=self.active == "logs")


__all__ = ["NavigationBar"]
