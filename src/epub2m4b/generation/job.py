"""Pure preparation of EPUB narration jobs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from epub2m4b.epub.cleaner import html_to_text
from epub2m4b.epub.parser import inspect_book
from epub2m4b.exceptions import EpubError
from epub2m4b.generation.chunker import chunk_text
from epub2m4b.generation.normalize import normalize_text
from epub2m4b.models import (
    Book,
    Chunk,
    JobManifest,
    JobStatus,
    ManifestBook,
    ManifestSource,
    NarrationSettings,
)


@dataclass(frozen=True, slots=True)
class PreparedJob:
    """The inspected, cleaned book and its in-memory durable manifest."""

    book: Book
    manifest: JobManifest

    @property
    def chapters(self):
        """Expose the prepared chapters without duplicating the book model."""

        return self.book.chapters

    @property
    def chunks(self) -> tuple[Chunk, ...]:
        return self.manifest.chunks


def prepare_job(
    source: Path,
    settings: NarrationSettings,
    job_id: str,
    app_version: str,
    timestamp: str | datetime,
) -> PreparedJob:
    """Inspect and prepare ``source`` without persistence, network, or providers."""

    book = inspect_book(Path(source))
    prepared_chapters = []
    all_chunks: list[Chunk] = []
    for chapter in book.chapters:
        text = normalize_text(html_to_text(chapter.html))
        prepared = replace(chapter, text=text)
        prepared_chapters.append(prepared)
        if chapter.included:
            all_chunks.extend(chunk_text(text, chapter_index=chapter.index, settings=settings))

    if not all_chunks:
        raise EpubError("EPUB contains no narratable chunks")

    prepared_book = replace(book, chapters=tuple(prepared_chapters))
    stamp = timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp
    manifest = JobManifest(
        job_id=job_id,
        app_version=app_version,
        source=ManifestSource(path=str(source), sha256=book.source_sha256),
        book=ManifestBook(title=book.title, authors=book.authors),
        narration=settings,
        chunks=tuple(all_chunks),
        status=JobStatus.READY,
        created_at=stamp,
        updated_at=stamp,
    )
    return PreparedJob(book=prepared_book, manifest=manifest)
