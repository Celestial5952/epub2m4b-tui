from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from epub2m4b.epub.parser import inspect_book
from epub2m4b.exceptions import EpubError


def make_epub(
    tmp_path: Path,
    *,
    items: list[tuple[str, str, str, str | None]] | None = None,
    spine: list[tuple[str, str]] | None = None,
    files: dict[str, str] | None = None,
    nav: str | None = None,
    package: str = "OPS/book.opf",
    toc: str | None = None,
) -> Path:
    items = items if items is not None else [("a", "a.xhtml", "application/xhtml+xml", None)]
    spine = spine if spine is not None else [(item[0], "yes") for item in items]
    files = (
        files
        if files is not None
        else {
            item[1]: f"<html><head><title>{item[0]}</title></head><body/></html>" for item in items
        }
    )
    manifest = "".join(
        f'<item id="{i}" href="{href}" media-type="{media}"'
        + (f' properties="{props}"' if props else "")
        + "/>"
        for i, href, media, props in items
    )
    itemrefs = "".join(f'<itemref idref="{i}" linear="{linear}"/>' for i, linear in spine)
    toc_attribute = f" toc='{toc}'" if toc else ""
    opf = f"""<package xmlns='http://www.idpf.org/2007/opf' version='3.0'>
      <metadata xmlns:dc='http://purl.org/dc/elements/1.1/'><dc:title>Test Book</dc:title></metadata>
      <manifest>{manifest}</manifest><spine{toc_attribute}>{itemrefs}</spine></package>"""
    path = tmp_path / "book.epub"
    with ZipFile(path, "w", ZIP_DEFLATED) as zf:
        zf.writestr(
            "META-INF/container.xml",
            f"<container><rootfiles><rootfile full-path='{package}'/></rootfiles></container>",
        )
        zf.writestr(package, opf)
        for name, value in files.items():
            if name.startswith("ROOT/"):
                archive_name = name.removeprefix("ROOT/")
            else:
                archive_name = name if name.startswith("OPS/") else f"OPS/{name}"
            zf.writestr(archive_name, value)
        if nav is not None:
            zf.writestr("OPS/nav.xhtml", nav)
    return path


def test_spine_order_titles_nav_and_determinism(tmp_path: Path) -> None:
    nav = """<html xmlns='http://www.w3.org/1999/xhtml' xmlns:epub='http://www.idpf.org/2007/ops'><body>
      <nav epub:type='landmarks'><ol><li><a href='text/a.xhtml'>Wrong</a></li></ol></nav>
      <nav epub:type='toc'><ol>
        <li><a href='text/a.xhtml?x=1#top'>Nav A</a></li>
        <li><a href='text/b.xhtml'>Nav B</a></li>
      </ol></nav>
    </body></html>"""
    source = make_epub(
        tmp_path,
        items=[
            ("b", "text/b.xhtml", "application/xhtml+xml", None),
            ("a", "text/a.xhtml", "application/xhtml+xml", None),
            ("nav", "nav.xhtml", "application/xhtml+xml", "nav"),
        ],
        spine=[("a", "yes"), ("b", "yes"), ("nav", "no")],
        files={
            "text/a.xhtml": "<html><head><title>Document A</title></head><body><h1>Heading A</h1></body></html>",
            "text/b.xhtml": "<html><body><h2>Heading B</h2></body></html>",
        },
        nav=nav,
    )
    first, second = inspect_book(source), inspect_book(source)
    assert [(c.index, c.title, c.source_href) for c in first.chapters] == [
        (0, "Nav A", "OPS/text/a.xhtml"),
        (1, "Nav B", "OPS/text/b.xhtml"),
    ]
    assert first == second
    assert first.source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()


def test_title_heading_and_final_fallback(tmp_path: Path) -> None:
    source = make_epub(
        tmp_path,
        items=[
            (x, f"{x}.xhtml", "application/xhtml+xml", None) for x in ("title", "h1", "h2", "plain")
        ],
        files={
            "title.xhtml": "<html><head><title>Title</title></head><body/></html>",
            "h1.xhtml": "<html><body><h1>One</h1></body></html>",
            "h2.xhtml": "<html><body><h2>Two</h2></body></html>",
            "plain.xhtml": "<html><body><p>Text</p></body></html>",
        },
    )
    assert [chapter.title for chapter in inspect_book(source).chapters] == [
        "Title",
        "One",
        "Two",
        "Chapter 4",
    ]


def test_relative_percent_encoded_query_fragment_and_non_xhtml(tmp_path: Path) -> None:
    source = make_epub(
        tmp_path,
        items=[
            ("one", "../Text/My%20Chapter.xhtml?x=1#x", "application/xhtml+xml", None),
            ("skip", "skip.pdf", "application/pdf", None),
        ],
        spine=[("one", "yes"), ("skip", "yes")],
        files={"ROOT/Text/My Chapter.xhtml": "<html><body/></html>", "skip.pdf": "pdf"},
    )
    chapter = inspect_book(source).chapters[0]
    assert chapter.source_href == "Text/My Chapter.xhtml"
    assert chapter.text == "" and chapter.included is True


def test_epub2_ncx_labels_group_continuation_documents(tmp_path: Path) -> None:
    ncx = """<ncx xmlns='http://www.daisy.org/z3986/2005/ncx/'>
      <navMap>
        <navPoint><navLabel><text>Introduction</text></navLabel><content src='intro.xhtml'/></navPoint>
        <navPoint><navLabel><text>Part One</text></navLabel><content src='part1-a.xhtml#start'/></navPoint>
        <navPoint><navLabel><text>Part Two</text></navLabel><content src='part2.xhtml'/></navPoint>
      </navMap>
    </ncx>"""
    source = make_epub(
        tmp_path,
        items=[
            ("intro", "intro.xhtml", "application/xhtml+xml", None),
            ("part1a", "part1-a.xhtml", "application/xhtml+xml", None),
            ("part1b", "part1-b.xhtml", "application/xhtml+xml", None),
            ("part2", "part2.xhtml", "application/xhtml+xml", None),
            ("ncx", "toc.ncx", "application/x-dtbncx+xml", None),
        ],
        spine=[
            ("intro", "yes"),
            ("part1a", "yes"),
            ("part1b", "yes"),
            ("part2", "yes"),
        ],
        files={
            "intro.xhtml": "<html><body>Intro</body></html>",
            "part1-a.xhtml": "<html><body>Part 1A</body></html>",
            "part1-b.xhtml": "<html><body>Part 1B</body></html>",
            "part2.xhtml": "<html><body>Part 2</body></html>",
            "toc.ncx": ncx,
        },
        toc="ncx",
    )

    chapters = inspect_book(source).chapters

    assert [chapter.title for chapter in chapters] == ["Introduction", "Part One", "Part Two"]
    assert chapters[1].source_href == "OPS/part1-a.xhtml"
    assert "Part 1A" in chapters[1].html
    assert "epub2m4b:document-boundary" in chapters[1].html
    assert "Part 1B" in chapters[1].html


@pytest.mark.parametrize(
    "href",
    [
        "http://example.com/a.xhtml",
        "//example.com/a.xhtml",
        "/a.xhtml",
        "..%2F..%2Fa.xhtml",
        "OPS\\a.xhtml",
        "a%00.xhtml",
    ],
)
def test_unsafe_href_rejected(tmp_path: Path, href: str) -> None:
    source = make_epub(tmp_path, items=[("a", href, "application/xhtml+xml", None)])
    with pytest.raises(EpubError):
        inspect_book(source)


def test_missing_structure_and_no_usable_chapters(tmp_path: Path) -> None:
    for spine in [[("missing", "yes")], []]:
        source = make_epub(
            tmp_path, items=[("a", "a.xhtml", "application/xhtml+xml", None)], spine=spine
        )
        with pytest.raises(EpubError):
            inspect_book(source)
    source = make_epub(tmp_path, items=[("a", "a.xhtml", "application/pdf", None)])
    with pytest.raises(EpubError, match="no usable"):
        inspect_book(source)


def test_missing_member_and_malformed_xml_rejected(tmp_path: Path) -> None:
    source = make_epub(
        tmp_path, items=[("a", "missing.xhtml", "application/xhtml+xml", None)], files={}
    )
    with pytest.raises(EpubError, match="missing"):
        inspect_book(source)
    source = make_epub(tmp_path, files={"a.xhtml": "<html"})
    assert inspect_book(source).chapters[0].html == "<html"
