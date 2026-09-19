from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from epub2m4b.exceptions import EpubError
from epub2m4b.generation.job import prepare_job
from epub2m4b.models import JobStatus, NarrationSettings


def _epub(path: Path, body: str) -> None:
    container = (
        '<container><rootfiles><rootfile full-path="OEBPS/package.opf"/></rootfiles></container>'
    )
    opf = '<package><metadata><title>Test &amp; Book</title><creator>Ada</creator></metadata><manifest><item id="c" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c"/></spine></package>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/package.opf", opf)
        archive.writestr("OEBPS/chapter.xhtml", body)


@pytest.fixture
def settings() -> NarrationSettings:
    return NarrationSettings("fake", "model", "voice", 1.0, "")


def test_prepare_job_is_deterministic_and_preserves_metadata(
    tmp_path: Path, settings: NarrationSettings
) -> None:
    source = tmp_path / "book.epub"
    _epub(
        source,
        "<html><title>Chapter title</title><body><h1>One</h1><p>Hello world.</p></body></html>",
    )
    first = prepare_job(source, settings, "job-1", "0.1", "2026-01-01T00:00:00Z")
    second = prepare_job(source, settings, "job-1", "0.1", "2026-01-01T00:00:00Z")
    assert first == second
    assert first.book.title == "Test & Book"
    assert first.book.chapters[0].index == 0
    assert first.book.chapters[0].title == "Chapter title"
    assert first.manifest.status is JobStatus.READY
    assert first.manifest.created_at == first.manifest.updated_at == "2026-01-01T00:00:00Z"
    assert first.manifest.source.sha256
    assert first.chunks[0].chapter_index == 0
    assert first.chunks[0].chunk_index == 0


def test_prepare_job_stores_normalized_chapter_text(
    tmp_path: Path, settings: NarrationSettings
) -> None:
    source = tmp_path / "whitespace.epub"
    _epub(source, "<html><body><p>First\r\n&nbsp;line.</p><p>Second</p><p>\u00a0</p></body></html>")
    prepared = prepare_job(source, settings, "job-1", "0.1", "now")
    assert prepared.book.chapters[0].text == "First\nline.\n\nSecond"
    assert prepared.chunks[0].text == "First\nline.\n\nSecond"


def test_prepare_job_rejects_empty_narration(tmp_path: Path, settings: NarrationSettings) -> None:
    source = tmp_path / "empty.epub"
    _epub(source, "<html><body><nav>Only navigation</nav><script>ignored</script></body></html>")
    with pytest.raises(EpubError, match="narratable"):
        prepare_job(source, settings, "job-1", "0.1", "now")
