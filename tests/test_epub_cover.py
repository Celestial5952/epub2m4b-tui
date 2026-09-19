from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from epub2m4b.epub.cover import CoverImage, read_cover
from epub2m4b.exceptions import EpubError

CONTAINER = """<?xml version="1.0"?><container><rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>"""


def _epub(tmp_path: Path, package: str, members: dict[str, bytes]) -> Path:
    target = tmp_path / "book.epub"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("META-INF/container.xml", CONTAINER)
        archive.writestr("OPS/package.opf", package)
        for name, data in members.items():
            archive.writestr(name, data)
    return target


def _package(manifest: str, metadata: str = "") -> str:
    return f"<package><metadata>{metadata}</metadata><manifest>{manifest}</manifest></package>"


def test_epub3_cover_takes_precedence(tmp_path: Path) -> None:
    package = _package(
        '<item id="fallback" href="fallback.png" media-type="image/png"/>'
        '<item id="cover" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>',
        '<meta name="cover" content="fallback"/>',
    )
    cover = read_cover(
        _epub(tmp_path, package, {"OPS/images/cover.jpg": b"jpeg", "OPS/fallback.png": b"png"})
    )
    assert cover == CoverImage("image/jpeg", ".jpg", b"jpeg")


def test_epub2_cover_declaration(tmp_path: Path) -> None:
    package = _package(
        '<item id="cover" href="images/cover.webp" media-type="image/webp"/>',
        '<meta name="cover" content="cover"/>',
    )
    cover = read_cover(_epub(tmp_path, package, {"OPS/images/cover.webp": b"webp"}))
    assert cover == CoverImage("image/webp", ".webp", b"webp")


def test_no_declared_cover_returns_none(tmp_path: Path) -> None:
    package = _package('<item id="text" href="text.xhtml" media-type="application/xhtml+xml"/>')
    assert read_cover(_epub(tmp_path, package, {"OPS/text.xhtml": b"text"})) is None


@pytest.mark.parametrize(
    ("href", "members"),
    [
        ("../cover.jpg", {"cover.jpg": b"x"}),
        ("https://example.test/cover.jpg", {}),
        ("missing.jpg", {}),
    ],
)
def test_unsafe_or_missing_cover_is_rejected(
    tmp_path: Path, href: str, members: dict[str, bytes]
) -> None:
    package = _package(
        f'<item id="cover" href="{href}" media-type="image/jpeg" properties="cover-image"/>'
    )
    with pytest.raises(EpubError):
        read_cover(_epub(tmp_path, package, members))


def test_unsupported_type_and_empty_cover_are_rejected(tmp_path: Path) -> None:
    unsupported = _package(
        '<item id="cover" href="cover.gif" media-type="image/gif" properties="cover-image"/>'
    )
    with pytest.raises(EpubError, match="unsupported media"):
        read_cover(_epub(tmp_path, unsupported, {"OPS/cover.gif": b"gif"}))
    empty = _package(
        '<item id="cover" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/>'
    )
    with pytest.raises(EpubError, match="empty"):
        read_cover(_epub(tmp_path, empty, {"OPS/cover.jpg": b""}))


def test_oversized_cover_rejected_before_read(tmp_path: Path) -> None:
    package = _package(
        '<item id="cover" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/>'
    )
    target = tmp_path / "book.epub"
    payload = tmp_path / "payload.epub"
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("META-INF/container.xml", CONTAINER)
        archive.writestr("OPS/package.opf", package)
        archive.writestr("OPS/cover.jpg", b"x" * (20 * 1024 * 1024 + 1))
    target.write_bytes(payload.read_bytes())
    with pytest.raises(EpubError, match="20 MiB"):
        read_cover(target)


def test_malformed_xml_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "broken.epub"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("META-INF/container.xml", "<container>")
    with pytest.raises(EpubError, match="invalid XML"):
        read_cover(target)
