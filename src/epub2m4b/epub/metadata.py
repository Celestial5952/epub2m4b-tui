"""Read package metadata from an EPUB without extracting its contents."""

from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from epub2m4b.exceptions import EpubError
from epub2m4b.models import BookMetadata


def _local_name(tag: str) -> str:
    """Return the local part of an XML expanded name."""

    return tag.rsplit("}", 1)[-1]


def _parse_xml(data: bytes, member: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise EpubError(f"invalid XML in EPUB member {member!r}") from exc


def _read_member(archive: zipfile.ZipFile, member: str) -> bytes:
    try:
        return archive.read(member)
    except KeyError as exc:
        raise EpubError(f"EPUB is missing required member {member!r}") from exc
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise EpubError(f"could not read EPUB member {member!r}") from exc


def _rootfile_path(value: str) -> str:
    """Validate and normalize a container rootfile path without touching disk."""

    if not value or "\x00" in value or "\\" in value:
        raise EpubError("container rootfile path is unsafe")
    if value.startswith("/"):
        raise EpubError("container rootfile path must be relative")
    parts = value.split("/")
    if any(part == ".." for part in parts):
        raise EpubError("container rootfile path must not contain '..'")
    # Empty and '.' components are harmless, but canonicalizing them makes the
    # member lookup unambiguous while retaining the archive's relative scope.
    normalized = posixpath.normpath(value)
    if normalized in ("", ".") or normalized.startswith("../"):
        raise EpubError("container rootfile path is unsafe")
    return normalized


def read_metadata(source: Path) -> BookMetadata:
    """Read required package metadata from *source*, an EPUB ZIP archive."""

    try:
        archive = zipfile.ZipFile(source, mode="r")
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise EpubError(f"could not open EPUB source {source}") from exc

    with archive:
        container_member = "META-INF/container.xml"
        container = _parse_xml(_read_member(archive, container_member), container_member)
        if _local_name(container.tag) != "container":
            raise EpubError("container.xml has an invalid root element")

        rootfile = next(
            (element for element in container.iter() if _local_name(element.tag) == "rootfile"),
            None,
        )
        if rootfile is None:
            raise EpubError("container.xml does not declare a rootfile")
        full_path = rootfile.get("full-path")
        if full_path is None:
            raise EpubError("container rootfile is missing its full-path")
        package_member = _rootfile_path(full_path)

        package = _parse_xml(_read_member(archive, package_member), package_member)
        if _local_name(package.tag) != "package":
            raise EpubError("package document has an invalid root element")
        metadata = next(
            (element for element in package if _local_name(element.tag) == "metadata"),
            None,
        )
        if metadata is None:
            raise EpubError("package document is missing its metadata element")

        def values(name: str) -> list[str]:
            return [
                text
                for child in metadata
                if _local_name(child.tag) == name
                if (text := "".join(child.itertext()).strip())
            ]

        title_values = values("title")
        if not title_values:
            raise EpubError("package metadata is missing a non-empty title")
        authors = tuple(values("creator"))

        def optional(name: str) -> str | None:
            found = values(name)
            return found[0] if found else None

        return BookMetadata(
            title=title_values[0],
            authors=authors,
            language=optional("language"),
            publisher=optional("publisher"),
            publication_date=optional("date"),
            identifier=optional("identifier"),
        )
