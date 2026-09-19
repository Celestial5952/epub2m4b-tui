from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from epub2m4b.epub.metadata import read_metadata
from epub2m4b.exceptions import EpubError


def make_epub(tmp_path: Path, *, package: str | None = None, container: str | None = None) -> Path:
    path = tmp_path / "book.epub"
    package = (
        package
        or """<?xml version='1.0'?>
        <package xmlns='http://www.idpf.org/2007/opf' version='3.0'>
          <metadata xmlns:dc='http://purl.org/dc/elements/1.1/'>
            <dc:title>  A Book  </dc:title>
            <dc:creator> First Author </dc:creator>
            <dc:creator>Second Author</dc:creator>
            <dc:language> en </dc:language><dc:publisher> Publisher </dc:publisher>
            <dc:date> 2024-01-02 </dc:date><dc:identifier> id-1 </dc:identifier>
          </metadata>
        </package>"""
    )
    container = (
        container
        or """<?xml version='1.0'?>
        <container xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>
          <rootfiles><rootfile full-path='OPS/content.opf' media-type='application/oebps-package+xml'/></rootfiles>
        </container>"""
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/content.opf", package)
    return path


def test_reads_full_metadata_and_preserves_creator_order(tmp_path: Path) -> None:
    metadata = read_metadata(make_epub(tmp_path))

    assert metadata.title == "A Book"
    assert metadata.authors == ("First Author", "Second Author")
    assert metadata.language == "en"
    assert metadata.publisher == "Publisher"
    assert metadata.publication_date == "2024-01-02"
    assert metadata.identifier == "id-1"


def test_reads_minimal_metadata_and_empty_optional_values_as_none(tmp_path: Path) -> None:
    package = """<package xmlns='http://www.idpf.org/2007/opf'><metadata xmlns:dc='http://purl.org/dc/elements/1.1/'>
        <dc:title> Title </dc:title><dc:language> </dc:language></metadata></package>"""
    metadata = read_metadata(make_epub(tmp_path, package=package))

    assert metadata.title == "Title"
    assert metadata.authors == ()
    assert metadata.language is None
    assert metadata.publisher is None
    assert metadata.publication_date is None
    assert metadata.identifier is None


@pytest.mark.parametrize(
    "source_factory, expected",
    [
        (lambda path: None, "could not open EPUB source"),
        (lambda path: path.write_text("not a zip"), "could not open EPUB source"),
    ],
)
def test_rejects_missing_or_non_zip_source(tmp_path: Path, source_factory, expected: str) -> None:
    source = tmp_path / "missing.epub"
    source_factory(source)
    with pytest.raises(EpubError, match=expected):
        read_metadata(source)


def test_rejects_malformed_xml(tmp_path: Path) -> None:
    source = make_epub(tmp_path, container="<container>")
    with pytest.raises(EpubError, match="invalid XML"):
        read_metadata(source)


@pytest.mark.parametrize(
    "container, package, expected",
    [
        ("<container/>", None, "does not declare a rootfile"),
        (None, "<not-package/>", "invalid root element"),
        (None, "<package><metadata/></package>", "missing a non-empty title"),
    ],
)
def test_rejects_missing_or_invalid_package_structure(
    tmp_path: Path, container: str | None, package: str | None, expected: str
) -> None:
    source = make_epub(tmp_path, container=container, package=package)
    with pytest.raises(EpubError, match=expected):
        read_metadata(source)


@pytest.mark.parametrize(
    "rootfile",
    ["/content.opf", "../content.opf", "OPS\\content.opf", "OPS/../content.opf", "OPS/\x00.opf"],
)
def test_rejects_unsafe_rootfile_paths(tmp_path: Path, rootfile: str) -> None:
    container = f"<container><rootfiles><rootfile full-path='{rootfile}'/></rootfiles></container>"
    source = make_epub(tmp_path, container=container)
    with pytest.raises(EpubError, match="unsafe|relative|must not|invalid XML"):
        read_metadata(source)
