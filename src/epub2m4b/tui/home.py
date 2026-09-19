"""Home screen for inspecting and preparing an EPUB through ApplicationService."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Select, Static

from epub2m4b.app.service import ApplicationService
from epub2m4b.exceptions import DuplicatePreparationError

from .navigation import NavigationBar

_SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class HomeScreen(Screen[None]):
    def __init__(self, service: ApplicationService, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.service = service
        self._source: Path | None = None
        self._book: Any = None
        self._busy = False
        self._library_available = False
        self._prepared_job_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="home"):
            yield NavigationBar("library")
            yield Static("EPUB2M4B Audiobook Studio", id="home-title")
            yield Static("1. Choose a book", classes="section-title")
            yield Static("Pick one from your book folder. We will open it automatically.")
            yield Static("Looking for EPUB books…", id="status")
            with Horizontal(id="library-row"):
                yield Select(
                    (),
                    prompt="Scanning configured book folder…",
                    id="library-select",
                    disabled=True,
                )
                yield Button("Refresh", id="refresh-library")
            yield Static("Book not listed? You can enter its full location here.")
            with Horizontal(id="source-row"):
                yield Input(placeholder="Book location", id="source-path")
                yield Button("Open book", id="inspect", variant="primary")
            yield Static("2. Check the book", classes="section-title")
            with VerticalScroll(id="book-details"):
                yield Static("Choose a book to see its title and chapters.", id="book-summary")
                yield Static("", id="chapter-list")
            yield Button(
                "3. Set up this audiobook",
                id="prepare",
                variant="success",
                disabled=True,
            )
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_library()

    async def refresh_library(self) -> None:
        selector = self.query_one("#library-select", Select)
        refresh = self.query_one("#refresh-library", Button)
        selector.disabled = True
        refresh.disabled = True
        try:
            scan = await self.service.scan_book_folder()
        except Exception:
            self._library_available = False
            selector.set_options(())
            selector.prompt = "Book folder unavailable"
            self._status("We could not open that book folder. Choose another folder.")
            return
        finally:
            refresh.disabled = False
        options = tuple((book.display_name, str(book.path)) for book in scan.books)
        self._library_available = bool(options)
        selector.set_options(options)
        selector.value = Select.BLANK
        if scan.root is None:
            selector.prompt = "No book folder configured"
            self._status("Choose a book folder to get started.")
        elif not options:
            selector.prompt = "No EPUB files found"
            self._status("No EPUB books were found. You can choose a different folder.")
        else:
            selector.prompt = "Choose an EPUB"
            selector.disabled = False
            suffix = " (showing the first results)" if scan.truncated else ""
            self._status(f"Found {len(options)} EPUB files{suffix}.")

    def _status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def _busy_state(self, busy: bool) -> None:
        self._busy = busy
        self.query_one("#source-path", Input).disabled = busy
        self.query_one("#inspect", Button).disabled = busy
        self.query_one("#library-select", Select).disabled = (
            busy or not self._library_available
        )
        self.query_one("#refresh-library", Button).disabled = busy
        self.query_one("#prepare", Button).disabled = (
            busy or self._book is None or self._prepared_job_id is not None
        )

    def _clear(self) -> None:
        self._book = None
        self._source = None
        self._prepared_job_id = None
        self.query_one("#book-summary", Static).update(
            "Choose a book to see its title and chapters."
        )
        self.query_one("#chapter-list", Static).update("")
        self.query_one("#prepare", Button).disabled = True

    def _error(self) -> None:
        self._status("We could not open that book. Make sure it is an EPUB file and try again.")

    async def inspect(self) -> None:
        if self._busy:
            return
        value = self.query_one("#source-path", Input).value.strip()
        self._clear()
        if not value:
            self._error()
            return
        self._source = Path(value)
        self._busy_state(True)
        self._status("Opening your book…")
        try:
            self._book = await self.service.inspect_book(self._source)
        except Exception:
            self._clear()
            self._error()
            return
        finally:
            self._busy_state(False)
        authors = ", ".join(str(author) for author in self._book.authors)
        summary_lines = [
            f"Title: {self._book.title}",
            f"Authors: {authors or 'Unknown author'}",
            f"Chapters: {len(self._book.chapters)}",
        ]
        if getattr(self._book, "language", None):
            summary_lines.append(f"Language: {self._book.language}")
        if getattr(self._book, "publisher", None):
            summary_lines.append(f"Publisher: {self._book.publisher}")
        if getattr(self._book, "publication_date", None):
            summary_lines.append(f"Published: {self._book.publication_date}")
        if getattr(self._book, "identifier", None):
            summary_lines.append(f"Identifier: {self._book.identifier}")
        if getattr(self._book, "cover_path", None):
            summary_lines.append("Cover art: Embedded cover image found")
        try:
            if self._source is not None and self._source.is_file():
                size = self._source.stat().st_size
                if size >= 1024 * 1024:
                    summary_lines.append(f"File size: {size / (1024 * 1024):.1f} MB")
                else:
                    summary_lines.append(f"File size: {size / 1024:.1f} KB")
        except OSError:
            pass
        if self._source is not None:
            summary_lines.append(f"Source file: {self._source}")
        self.query_one("#book-summary", Static).update("\n".join(summary_lines))
        self.query_one("#chapter-list", Static).update(
            "\n".join(f"{chapter.index + 1}. {chapter.title}" for chapter in self._book.chapters)
        )
        self.query_one("#prepare", Button).disabled = False
        self._status("Book ready. Check the chapters, then set up your audiobook.")

    async def prepare(self) -> None:
        if self._busy or self._book is None or self._source is None:
            return
        self._busy_state(True)
        self._status("Setting up your audiobook…")
        try:
            job = await self.service.create_job(self._source)
        except DuplicatePreparationError as exc:
            self._prepared_job_id = exc.existing_job_id
            self.query_one("#prepare", Button).disabled = True
            self._status(
                "This book is already set up. Open Jobs to continue — "
                f"Reference: {exc.existing_job_id}"
            )
            return
        except Exception:
            self._error()
            return
        finally:
            self._busy_state(False)
        job_id = str(getattr(job, "job_id", "created"))
        safe_id = job_id if _SAFE_JOB_ID.fullmatch(job_id) else "created"
        self._prepared_job_id = safe_id
        self.query_one("#prepare", Button).disabled = True
        self._status(
            f"Audiobook setup is ready. Open Jobs to review it. Reference: {safe_id}"
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "inspect":
            await self.inspect()
        elif event.button.id == "refresh-library":
            await self.refresh_library()
        elif event.button.id == "prepare":
            await self.prepare()
        elif event.button.id == "nav-jobs":
            self.app.show_jobs()  # type: ignore[attr-defined]
        elif event.button.id == "nav-voices":
            self.app.show_voices()  # type: ignore[attr-defined]
        elif event.button.id == "nav-settings":
            self.app.show_settings()  # type: ignore[attr-defined]
        elif event.button.id == "nav-logs":
            self.app.show_logs()  # type: ignore[attr-defined]

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "source-path":
            await self.inspect()

    async def on_select_changed(self, event: Select.Changed[str]) -> None:
        if event.select.id == "library-select" and event.value is not Select.BLANK:
            self.query_one("#source-path", Input).value = str(event.value)
            await self.inspect()


__all__ = ["HomeScreen"]
