from pathlib import Path

import pytest

from epub2m4b.app.library import scan_epub_folder
from epub2m4b.exceptions import LibraryError


def test_recursive_scan_is_sorted_and_ignores_non_epubs_and_symlinks(
    tmp_path: Path,
) -> None:
    (tmp_path / "zeta").mkdir()
    (tmp_path / "Alpha").mkdir()
    (tmp_path / "zeta" / "Second.EPUB").write_bytes(b"epub")
    (tmp_path / "Alpha" / "first.epub").write_bytes(b"epub")
    (tmp_path / "notes.txt").write_text("not a book", encoding="utf-8")
    (tmp_path / "linked.epub").symlink_to(tmp_path / "Alpha" / "first.epub")
    (tmp_path / "linked-dir").symlink_to(tmp_path / "zeta", target_is_directory=True)

    scan = scan_epub_folder(tmp_path)

    assert scan.root == tmp_path.resolve()
    assert [book.relative_path for book in scan.books] == [
        Path("Alpha/first.epub"),
        Path("zeta/Second.EPUB"),
    ]
    assert [book.display_name for book in scan.books] == [
        "Alpha/first.epub",
        "zeta/Second.EPUB",
    ]
    assert not scan.truncated


def test_scan_is_bounded_deterministically(tmp_path: Path) -> None:
    for name in ("c.epub", "A.epub", "b.epub"):
        (tmp_path / name).write_bytes(b"book")

    scan = scan_epub_folder(tmp_path, max_books=2)

    assert [book.relative_path for book in scan.books] == [Path("A.epub"), Path("b.epub")]
    assert scan.truncated


def test_unavailable_or_non_directory_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(LibraryError, match="unavailable"):
        scan_epub_folder(tmp_path / "missing")
    file_path = tmp_path / "file"
    file_path.write_bytes(b"x")
    with pytest.raises(LibraryError, match="not a directory"):
        scan_epub_folder(file_path)


@pytest.mark.parametrize("maximum", [0, -1, True, 1.5])
def test_maximum_must_be_positive_integer(tmp_path: Path, maximum: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        scan_epub_folder(tmp_path, max_books=maximum)  # type: ignore[arg-type]
