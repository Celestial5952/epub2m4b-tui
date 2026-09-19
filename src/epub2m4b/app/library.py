"""Bounded, read-only discovery of EPUB files in a listener's library."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from epub2m4b.exceptions import LibraryError

DEFAULT_MAX_BOOKS = 10_000


@dataclass(frozen=True, slots=True)
class LibraryBook:
    path: Path
    relative_path: Path

    @property
    def display_name(self) -> str:
        return str(self.relative_path)


@dataclass(frozen=True, slots=True)
class LibraryScan:
    root: Path | None
    books: tuple[LibraryBook, ...]
    truncated: bool = False


def scan_epub_folder(root: Path, *, max_books: int = DEFAULT_MAX_BOOKS) -> LibraryScan:
    """Recursively list regular EPUB files without following symbolic links."""

    if isinstance(max_books, bool) or not isinstance(max_books, int) or max_books <= 0:
        raise ValueError("maximum books must be a positive integer")
    try:
        resolved = Path(root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        raise LibraryError("book folder is unavailable") from None
    if not resolved.is_dir():
        raise LibraryError("book folder is not a directory")

    discovered: list[LibraryBook] = []
    stack = [resolved]
    truncated = False
    while stack:
        directory = stack.pop()
        try:
            entries = tuple(
                sorted(
                    os.scandir(directory),
                    key=lambda entry: (entry.name.casefold(), entry.name),
                )
            )
        except OSError:
            continue
        child_directories: list[Path] = []
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    child_directories.append(path)
                elif entry.is_file(follow_symlinks=False) and path.suffix.casefold() == ".epub":
                    if len(discovered) == max_books:
                        truncated = True
                        continue
                    discovered.append(LibraryBook(path, path.relative_to(resolved)))
            except OSError:
                continue
        stack.extend(
            sorted(child_directories, key=lambda path: str(path).casefold(), reverse=True)
        )

    discovered.sort(
        key=lambda item: (str(item.relative_path).casefold(), str(item.relative_path))
    )
    return LibraryScan(resolved, tuple(discovered), truncated)


__all__ = ["DEFAULT_MAX_BOOKS", "LibraryBook", "LibraryScan", "scan_epub_folder"]
