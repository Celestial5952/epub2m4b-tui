"""Conservative conversion of EPUB markup to narration text."""

from __future__ import annotations

import re
from html.parser import HTMLParser

_SKIP_TAGS = frozenset({"script", "style", "noscript", "nav", "svg", "template"})
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_BOUNDARY_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "header",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "blockquote",
        "pre",
    }
)
_PAGE_MARKER = re.compile(
    r"(?:^|[^a-z0-9])(?:page[_-]?break|doc[_-]?page[_-]?break|page[_-]?(?:num|number)|pagenumber)(?:$|[^a-z0-9])",
    re.IGNORECASE,
)


def _attr_map(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    return {name.lower(): (value or "") for name, value in attrs}


def _is_page_marker(tag: str, attrs: dict[str, str]) -> bool:
    values = " ".join(
        attrs.get(name, "") for name in ("id", "class", "epub:type", "role", "aria-label")
    )
    return bool(_PAGE_MARKER.search(values)) or tag in {
        "pagebreak",
        "page-break",
        "doc-pagebreak",
        "doc-page-break",
        "pagenum",
    }


def _is_hidden(attrs: dict[str, str]) -> bool:
    if "hidden" in attrs or attrs.get("aria-hidden", "").strip().lower() == "true":
        return True
    for declaration in attrs.get("style", "").split(";"):
        if ":" not in declaration:
            continue
        property_name, value = declaration.split(":", 1)
        property_name = property_name.strip().lower()
        value = value.strip().lower()
        if value.endswith("!important"):
            value = value[: -len("!important")].rstrip()
        if (property_name, value) in {("display", "none"), ("visibility", "hidden")}:
            return True
    return False


class _NarrationParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._frames: list[tuple[str, bool]] = []

    def _break(self, count: int) -> None:
        if not self.parts:
            return
        existing = len(self.parts[-1]) - len(self.parts[-1].rstrip("\n"))
        if existing < count:
            self.parts.append("\n" * (count - existing))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = _attr_map(attrs)
        skipped = bool(self._frames and self._frames[-1][1])
        skipped = skipped or tag in _SKIP_TAGS or _is_hidden(values) or _is_page_marker(tag, values)
        if tag not in _VOID_TAGS:
            self._frames.append((tag, skipped))
        if skipped:
            return
        if tag in _BOUNDARY_TAGS:
            self._break(2)
        elif tag == "br":
            self._break(1)
        elif tag == "hr":
            self._break(2)
            self.parts.append("* * *")
            self._break(2)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        try:
            index = len(self._frames) - 1 - [frame[0] for frame in self._frames][::-1].index(tag)
        except ValueError:
            return
        matched_was_skipped = self._frames[index][1]
        self._frames = self._frames[:index]
        if not matched_was_skipped and tag in _BOUNDARY_TAGS:
            self._break(2)

    def handle_data(self, data: str) -> None:
        if not any(frame[1] for frame in self._frames):
            self.parts.append(data)

    def handle_comment(self, data: str) -> None:
        if (
            not any(frame[1] for frame in self._frames)
            and data.strip().lower() == "epub2m4b:document-boundary"
        ):
            self._break(2)


def html_to_text(markup: str) -> str:
    """Return visible, source-ordered prose extracted from HTML/XHTML."""

    parser = _NarrationParser()
    parser.feed(markup)
    parser.close()
    return "".join(parser.parts)
