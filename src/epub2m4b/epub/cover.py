"""Discover a declared EPUB cover without extracting archive members."""

from __future__ import annotations

import posixpath
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from epub2m4b.epub.metadata import _local_name, _parse_xml, _read_member, _rootfile_path
from epub2m4b.epub.parser import _safe_href
from epub2m4b.exceptions import EpubError

_MAX_COVER_BYTES = 20 * 1024 * 1024
_MEDIA_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


@dataclass(frozen=True, slots=True)
class CoverImage:
    """The immutable bytes and declared type of an EPUB cover image."""

    media_type: str
    suffix: str
    data: bytes


def _selected_item(package: ElementTree.Element) -> tuple[str, str, str] | None:
    manifest = next((child for child in package if _local_name(child.tag) == "manifest"), None)
    if manifest is None:
        raise EpubError("package document is missing its manifest element")

    items: dict[str, tuple[str, str]] = {}
    cover_item: tuple[str, str, str] | None = None
    for item in manifest:
        if _local_name(item.tag) != "item":
            continue
        item_id = item.get("id")
        href = item.get("href")
        media_type = item.get("media-type")
        if not item_id or href is None or media_type is None:
            raise EpubError("manifest item is missing required attributes")
        items[item_id] = (href, media_type)
        properties = (item.get("properties") or "").split()
        if cover_item is None and "cover-image" in properties:
            cover_item = (item_id, href, media_type)

    # EPUB 3's declaration has precedence, even when an EPUB 2 meta fallback
    # is also present.
    if cover_item is not None:
        return cover_item

    metadata = next((child for child in package if _local_name(child.tag) == "metadata"), None)
    if metadata is None:
        return None
    for element in metadata:
        if _local_name(element.tag) != "meta" or element.get("name") != "cover":
            continue
        cover_id = element.get("content")
        if not cover_id or cover_id not in items:
            raise EpubError("EPUB cover declaration references a missing manifest item")
        href, media_type = items[cover_id]
        return cover_id, href, media_type
    return None


def read_cover(source: Path) -> CoverImage | None:
    """Read the declared raster cover from *source*, without extraction."""

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
        if rootfile is None or not rootfile.get("full-path"):
            raise EpubError("container.xml does not declare a rootfile")
        package_member = _rootfile_path(rootfile.get("full-path", ""))
        package = _parse_xml(_read_member(archive, package_member), package_member)
        if _local_name(package.tag) != "package":
            raise EpubError("package document has an invalid root element")
        selected = _selected_item(package)
        if selected is None:
            return None
        _, href, media_type = selected
        normalized_type = media_type.lower()
        suffix = _MEDIA_SUFFIXES.get(normalized_type)
        if suffix is None:
            raise EpubError("EPUB cover uses an unsupported media type")
        package_dir = posixpath.dirname(package_member)
        parsed_href = urlsplit(href)
        if any(part == ".." for part in unquote(parsed_href.path).split("/")):
            raise EpubError("EPUB cover href must not contain '..'")
        member = _safe_href(href, package_dir)
        try:
            info = archive.getinfo(member)
        except KeyError as exc:
            raise EpubError(f"EPUB is missing declared cover member {member!r}") from exc
        if info.file_size <= 0:
            raise EpubError("EPUB cover member is empty")
        if info.file_size > _MAX_COVER_BYTES:
            raise EpubError("EPUB cover member exceeds the 20 MiB limit")
        try:
            data = archive.read(info)
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise EpubError("could not read declared EPUB cover") from exc
        if not data:
            raise EpubError("EPUB cover member is empty")
        return CoverImage(media_type=normalized_type, suffix=suffix, data=data)
