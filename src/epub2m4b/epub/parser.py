"""Discover the reading order and source documents in an EPUB."""

from __future__ import annotations

import hashlib
import posixpath
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from epub2m4b.epub.metadata import _local_name, _parse_xml, _read_member, read_metadata
from epub2m4b.exceptions import EpubError
from epub2m4b.models import Book, Chapter

_HTML_MEDIA_TYPES = {"application/xhtml+xml", "text/html"}
_DOCUMENT_BOUNDARY = "\n<!-- epub2m4b:document-boundary -->\n"


def _safe_href(href: str, base: str) -> str:
    """Resolve an archive-relative URI, rejecting paths that leave the archive."""

    if not href or "\x00" in href or "\\" in href:
        raise EpubError("EPUB item href is unsafe")
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        raise EpubError("EPUB item href must be local")
    path = unquote(parsed.path)
    if "\x00" in path or "\\" in path or path.startswith("/"):
        raise EpubError("EPUB item href is unsafe")
    joined = posixpath.normpath(posixpath.join(base, path))
    if joined in ("", ".") or joined.startswith("../") or joined == "..":
        raise EpubError("EPUB item href must not traverse the archive")
    return joined


def _markup_title(markup: bytes) -> str | None:
    """Extract the document title or first heading when the document is XML."""

    try:
        root = ElementTree.fromstring(markup)
    except ElementTree.ParseError:
        return None
    for element in root.iter():
        if _local_name(element.tag) == "title":
            value = " ".join("".join(element.itertext()).split())
            if value:
                return value
    for element in root.iter():
        if _local_name(element.tag) in {"h1", "h2"}:
            value = " ".join("".join(element.itertext()).split())
            if value:
                return value
    return None


def _nav_labels(markup: bytes, nav_member: str) -> dict[str, str]:
    """Return normalized chapter-member to label mappings from an EPUB nav file."""

    try:
        root = ElementTree.fromstring(markup)
    except ElementTree.ParseError:
        return {}
    labels: dict[str, str] = {}
    nav_dir = posixpath.dirname(nav_member)
    toc_navs = []
    for element in root.iter():
        if _local_name(element.tag) != "nav":
            continue
        epub_type = element.get("{http://www.idpf.org/2007/ops}type") or element.get(
            "epub:type", ""
        )
        if "toc" in epub_type.split():
            toc_navs.append(element)
    for nav in toc_navs:
        anchors = nav.iter()
        for anchor in anchors:
            if _local_name(anchor.tag) != "a":
                continue
            href = anchor.get("href")
            if not href:
                continue
            try:
                target = _safe_href(href, nav_dir)
            except EpubError:
                continue
            label = " ".join("".join(anchor.itertext()).split())
            if label and target not in labels:
                labels[target] = label
    return labels


def _ncx_labels(markup: bytes, ncx_member: str) -> dict[str, str]:
    """Return ordered member-to-label mappings from an EPUB 2 NCX document."""

    root = _parse_xml(markup, ncx_member)
    if _local_name(root.tag) != "ncx":
        raise EpubError("NCX document has an invalid root element")
    labels: dict[str, str] = {}
    ncx_dir = posixpath.dirname(ncx_member)
    for nav_point in root.iter():
        if _local_name(nav_point.tag) != "navPoint":
            continue
        nav_label = next(
            (child for child in nav_point if _local_name(child.tag) == "navLabel"),
            None,
        )
        content = next(
            (child for child in nav_point if _local_name(child.tag) == "content"),
            None,
        )
        if nav_label is None or content is None or not content.get("src"):
            continue
        label = " ".join("".join(nav_label.itertext()).split())
        if not label:
            continue
        try:
            target = _safe_href(content.get("src", ""), ncx_dir)
        except EpubError:
            continue
        labels.setdefault(target, label)
    return labels


def _document_encoding(data: bytes) -> str:
    """Use an XML-declared encoding when present, otherwise EPUB's UTF-8 default."""

    declaration = re.match(rb"\s*<\?xml[^>]*encoding=[\"']([^\"']+)[\"']", data)
    return declaration.group(1).decode("ascii", errors="ignore") if declaration else "utf-8"


def inspect_book(source: Path) -> Book:
    """Inspect an EPUB and return its metadata and spine-ordered chapters."""

    metadata = read_metadata(source)
    try:
        source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        archive = zipfile.ZipFile(source, mode="r")
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise EpubError(f"could not open EPUB source {source}") from exc

    with archive:
        container_member = "META-INF/container.xml"
        container = _parse_xml(_read_member(archive, container_member), container_member)
        rootfile = next(
            (element for element in container.iter() if _local_name(element.tag) == "rootfile"),
            None,
        )
        if rootfile is None or not rootfile.get("full-path"):
            raise EpubError("container.xml does not declare a rootfile")
        package_member = rootfile.get("full-path")
        # read_metadata has already validated this path; normalize for joining hrefs.
        if package_member is None:
            raise EpubError("container rootfile is missing its full-path")
        package_member = posixpath.normpath(package_member)
        package = _parse_xml(_read_member(archive, package_member), package_member)
        if _local_name(package.tag) != "package":
            raise EpubError("package document has an invalid root element")
        package_dir = posixpath.dirname(package_member)
        manifest = next((e for e in package if _local_name(e.tag) == "manifest"), None)
        spine = next((e for e in package if _local_name(e.tag) == "spine"), None)
        if manifest is None or spine is None:
            raise EpubError("package document is missing its manifest or spine")

        items: dict[str, tuple[str, str]] = {}
        nav_item: tuple[str, str] | None = None
        for item in manifest:
            if _local_name(item.tag) != "item":
                continue
            item_id, href, media_type = item.get("id"), item.get("href"), item.get("media-type")
            if not item_id or href is None or media_type is None:
                raise EpubError("manifest item is missing required attributes")
            member = _safe_href(href, package_dir)
            items[item_id] = (member, media_type.lower())
            if "nav" in (item.get("properties") or "").split():
                nav_item = (member, media_type.lower())

        toc_labels: dict[str, str] = {}
        if nav_item is not None:
            nav_member, _ = nav_item
            if nav_member not in archive.namelist():
                raise EpubError(f"EPUB is missing manifest member {nav_member!r}")
            toc_labels = _nav_labels(_read_member(archive, nav_member), nav_member)
        elif spine.get("toc"):
            toc_id = spine.get("toc", "")
            if toc_id not in items:
                raise EpubError("spine references a missing NCX manifest item")
            ncx_member, ncx_media_type = items[toc_id]
            if ncx_media_type != "application/x-dtbncx+xml":
                raise EpubError("spine TOC item is not an NCX document")
            if ncx_member not in archive.namelist():
                raise EpubError(f"EPUB is missing manifest member {ncx_member!r}")
            toc_labels = _ncx_labels(_read_member(archive, ncx_member), ncx_member)

        documents: list[tuple[str, bytes, str]] = []
        for itemref in spine:
            if (
                _local_name(itemref.tag) != "itemref"
                or itemref.get("linear", "yes").lower() == "no"
            ):
                continue
            idref = itemref.get("idref")
            if not idref or idref not in items:
                raise EpubError("spine references a missing manifest item")
            member, media_type = items[idref]
            if member not in archive.namelist():
                raise EpubError(f"EPUB is missing manifest member {member!r}")
            if media_type not in _HTML_MEDIA_TYPES:
                continue
            markup = _read_member(archive, member)
            try:
                html = markup.decode(_document_encoding(markup))
            except (LookupError, UnicodeDecodeError) as exc:
                raise EpubError(f"could not decode EPUB member {member!r}") from exc
            documents.append((member, markup, html))
        if not documents:
            raise EpubError("EPUB contains no usable chapters")

        groups: list[tuple[str, list[tuple[str, bytes, str]]]] = []
        matched_toc = any(member in toc_labels for member, _, _ in documents)
        for member, markup, html in documents:
            toc_title = toc_labels.get(member) if matched_toc else None
            if not groups or toc_title is not None or not matched_toc:
                fallback = _markup_title(markup)
                title = toc_title or fallback or f"Chapter {len(groups) + 1}"
                groups.append((title, [(member, markup, html)]))
            else:
                groups[-1][1].append((member, markup, html))

        chapters: list[Chapter] = []
        for index, (title, group_documents) in enumerate(groups):
            chapters.append(
                Chapter(
                    index=index,
                    title=title,
                    source_href=group_documents[0][0],
                    html=_DOCUMENT_BOUNDARY.join(document[2] for document in group_documents),
                    text="",
                    included=True,
                )
            )

    return Book(
        source_path=source,
        source_sha256=source_sha256,
        title=metadata.title,
        authors=metadata.authors,
        language=metadata.language,
        publisher=metadata.publisher,
        publication_date=metadata.publication_date,
        identifier=metadata.identifier,
        cover_path=None,
        chapters=tuple(chapters),
    )
