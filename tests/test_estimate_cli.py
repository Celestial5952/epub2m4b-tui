from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from epub2m4b import cli
from epub2m4b.estimate_cli import (
    BookReport,
    collect_epubs,
    format_duration,
    render_report,
    run_estimate,
)
from epub2m4b.generation.comparison import compare_providers
from epub2m4b.models import Chunk, NarrationSettings


def _epub(path: Path, title: str, *bodies: str) -> Path:
    """Write a minimal EPUB whose chapters are bare paragraphs of the given text."""

    container = (
        '<container><rootfiles><rootfile full-path="OEBPS/package.opf"/></rootfiles></container>'
    )
    manifest = "".join(
        f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>'
        for i in range(len(bodies))
    )
    spine = "".join(f'<itemref idref="c{i}"/>' for i in range(len(bodies)))
    opf = (
        f"<package><metadata><title>{title}</title><creator>Ada</creator></metadata>"
        f"<manifest>{manifest}</manifest><spine>{spine}</spine></package>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/package.opf", opf)
        for i, body in enumerate(bodies):
            archive.writestr(f"OEBPS/c{i}.xhtml", f"<html><body><p>{body}</p></body></html>")
    return path


def _run(source: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    status = run_estimate(source, out, err)
    return status, out.getvalue(), err.getvalue()


def test_single_epub_reports_exact_text_size_and_every_provider(tmp_path: Path) -> None:
    # 500 words fit in one chunk: 2,499 characters (trailing space trimmed) and
    # 250 seconds of listening at 120 words per minute.
    book = _epub(tmp_path / "small.epub", "Small Book", "word " * 500)

    status, out, err = _run(book)

    assert status == 0
    assert err == ""
    assert "no requests were made and no API key was read" in out
    assert "Small Book" in out
    assert "2,499" in out and "0h 04m" in out
    for label in ("OpenAI gpt-4o-mini-tts", "ElevenLabs Multilingual v2", "ElevenLabs Flash v2.5"):
        assert label in out
    # OpenAI $0.07; Multilingual $0.29 / 2,874 credits (Free); Flash $0.15 / 1,437 credits.
    assert "$0.07" in out and "$0.29" in out and "$0.15" in out
    assert "2,874 (Free)" in out and "1,437 (Free)" in out
    assert "UNTESTED live" in out and "elevenlabs.io/pricing" in out


def test_folder_reports_each_book_and_a_combined_total(tmp_path: Path) -> None:
    _epub(tmp_path / "a.epub", "Alpha", "word " * 500)
    nested = tmp_path / "more"
    nested.mkdir()
    # Each chapter fits one chunk: 2,999 characters apiece.
    _epub(nested / "b.epub", "Beta", "word " * 600, "word " * 600)
    (tmp_path / "notes.txt").write_text("ignored")

    status, out, _ = _run(tmp_path)

    assert status == 0
    assert "Alpha" in out and "Beta" in out
    assert "Total (2 books)" in out
    assert "All books in one month" in out
    # 2,499 + 2 * 2,999 characters and 500 + 1,200 words, combined.
    assert "8,497" in out and "1,700" in out


def test_unreadable_epub_is_skipped_and_reported_but_others_still_estimate(
    tmp_path: Path,
) -> None:
    _epub(tmp_path / "good.epub", "Good Book", "word " * 100)
    (tmp_path / "bad.epub").write_bytes(b"not a zip")

    status, out, err = _run(tmp_path)

    assert status == 1  # a skipped file is a failure, but the report is still printed
    assert "skipped bad.epub" in err
    assert "Good Book" in out


def test_empty_folder_and_missing_path_fail_with_a_clear_message(tmp_path: Path) -> None:
    status, out, err = _run(tmp_path)
    assert (status, out) == (1, "")
    assert "no EPUB files found" in err

    status, out, err = _run(tmp_path / "missing")
    assert (status, out) == (1, "")
    assert "no such file or folder" in err


def test_only_unreadable_epubs_prints_no_report(tmp_path: Path) -> None:
    (tmp_path / "bad.epub").write_bytes(b"nope")
    status, out, err = _run(tmp_path)
    assert (status, out) == (1, "")
    assert "skipped bad.epub" in err


def test_collect_epubs_accepts_a_file_or_scans_a_folder(tmp_path: Path) -> None:
    one = _epub(tmp_path / "one.epub", "One", "hello")
    assert collect_epubs(one) == (one,)
    assert [p.name for p in collect_epubs(tmp_path)] == ["one.epub"]


def test_render_report_layout_is_stable() -> None:
    settings = NarrationSettings("openai", "gpt-4o-mini-tts", "marin", 1.0, "")
    chunk = Chunk.create(chapter_index=0, chunk_index=0, text="word " * 20_000, settings=settings)
    report = BookReport("A Long Title " * 6, 3, (chunk,), compare_providers((chunk,)))

    text = render_report([report])

    assert "Total" not in text  # one book needs no total row
    assert "A Long Title A Long Title A Long Titl…" in text  # titles are clipped
    assert "$2.78" in text and "$11.50" in text and "$5.75" in text
    assert "115,000 (Pro)" in text and "57,500 (Creator)" in text
    assert text.endswith("confirm at https://elevenlabs.io/pricing.\n")


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, "0h 00m"), (1, "0h 01m"), (1_000, "0h 17m"), (10_004, "2h 47m"), (3_600, "1h 00m")],
)
def test_format_duration(seconds: int, expected: str) -> None:
    assert format_duration(seconds) == expected


def test_estimate_subcommand_runs_without_creating_the_application_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Forbidden:
        @classmethod
        def create_default(cls) -> object:
            raise AssertionError("estimate must not load credentials or app state")

    class ForbiddenApp:
        def __init__(self, service: object) -> None:
            raise AssertionError("estimate must not start the TUI")

    monkeypatch.setattr(cli, "LocalApplicationService", Forbidden)
    monkeypatch.setattr(cli, "EPUB2M4BApp", ForbiddenApp)
    book = _epub(tmp_path / "book.epub", "CLI Book", "word " * 500)

    assert cli.main(["estimate", str(book)]) == 0

    captured = capsys.readouterr()
    assert "CLI Book" in captured.out
    assert captured.err == ""


def test_estimate_subcommand_returns_failure_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["estimate", str(tmp_path / "missing")]) == 1
    assert "no such file or folder" in capsys.readouterr().err


def test_estimate_requires_a_path_and_help_lists_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["estimate"])
    assert caught.value.code == 2
    capsys.readouterr()
    with pytest.raises(SystemExit) as caught:
        cli.main(["--help"])
    assert caught.value.code == 0
    assert "estimate" in capsys.readouterr().out
