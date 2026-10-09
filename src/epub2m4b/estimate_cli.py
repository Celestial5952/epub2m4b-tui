"""``epub2m4b estimate``: offline text-size and cost report for EPUB files."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TextIO

from epub2m4b import __version__
from epub2m4b.app.library import scan_epub_folder
from epub2m4b.exceptions import Epub2M4BError
from epub2m4b.generation.comparison import (
    ProviderComparison,
    ProviderQuote,
    compare_providers,
    format_usd,
)
from epub2m4b.generation.estimate import DEFAULT_SAFETY_MULTIPLIER, DEFAULT_WORDS_PER_MINUTE
from epub2m4b.generation.job import prepare_job
from epub2m4b.models import Chunk, NarrationSettings

_TITLE_WIDTH = 38
# Chunk identity is irrelevant to an estimate; any valid settings give the same text.
_SETTINGS = NarrationSettings("openai", "gpt-4o-mini-tts", "marin", 1.0, "")


@dataclass(frozen=True, slots=True)
class BookReport:
    title: str
    chapters: int
    chunks: tuple[Chunk, ...]
    comparison: ProviderComparison


def format_duration(seconds: int) -> str:
    minutes = max(1, round(seconds / 60)) if seconds else 0
    hours, rest = divmod(minutes, 60)
    return f"{hours}h {rest:02d}m"


def collect_epubs(source: Path) -> tuple[Path, ...]:
    """Return the EPUB(s) to estimate: one file, or every EPUB under a folder."""

    path = Path(source).expanduser()
    if path.is_dir():
        return tuple(book.path for book in scan_epub_folder(path).books)
    if path.is_file():
        return (path,)
    raise FileNotFoundError(f"no such file or folder: {path}")


def _report(path: Path) -> BookReport:
    prepared = prepare_job(path, _SETTINGS, "estimate", __version__, "estimate")
    chunks = prepared.chunks
    return BookReport(
        title=prepared.book.title or path.stem,
        chapters=sum(1 for chapter in prepared.chapters if chapter.included),
        chunks=chunks,
        comparison=compare_providers(chunks),
    )


def _clip(text: str, width: int = _TITLE_WIDTH) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def _table(
    headers: Sequence[str], rows: Sequence[Sequence[str]], numeric: Sequence[bool]
) -> list[str]:
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))
    ]

    def line(cells: Sequence[str]) -> str:
        parts = [
            cell.rjust(widths[i]) if numeric[i] else cell.ljust(widths[i])
            for i, cell in enumerate(cells)
        ]
        return "  " + "  ".join(parts).rstrip()

    rule = "  " + "  ".join("-" * width for width in widths)
    return [line(headers), rule, *(line(row) for row in rows)]


def _credit_cell(quote: ProviderQuote) -> str:
    plan = quote.smallest_plan or "beyond Business"
    return f"{quote.credits:,} ({plan})"


def render_report(reports: Sequence[BookReport]) -> str:
    """Format the full multi-book report. Pure, so it can be tested directly."""

    total_chunks = tuple(chunk for report in reports for chunk in report.chunks)
    total = compare_providers(total_chunks)
    many = len(reports) > 1
    lines = [
        "Offline estimate: no requests were made and no API key was read.",
        f"Prices include a {int((Decimal(DEFAULT_SAFETY_MULTIPLIER) - 1) * 100)}% safety "
        f"margin; audio length assumes {DEFAULT_WORDS_PER_MINUTE} words per minute.",
        "",
        "TEXT",
    ]

    rows = [
        [
            _clip(r.title),
            f"{r.chapters:,}",
            f"{r.comparison.word_count:,}",
            f"{r.comparison.character_count:,}",
            format_duration(r.comparison.estimated_seconds),
        ]
        for r in reports
    ]
    if many:
        rows.append(
            [
                f"Total ({len(reports)} books)",
                f"{sum(r.chapters for r in reports):,}",
                f"{total.word_count:,}",
                f"{total.character_count:,}",
                format_duration(total.estimated_seconds),
            ]
        )
    lines += _table(
        ["Title", "Chapters", "Words", "Characters", "Audio"],
        rows,
        [False, True, True, True, True],
    )

    targets = [quote.target for quote in total.quotes]
    lines += ["", "ESTIMATED COST (USD)"]
    cost_rows = [
        [_clip(r.title), *(format_usd(q.estimated_cost_usd) for q in r.comparison.quotes)]
        for r in reports
    ]
    if many:
        cost_rows.append(
            ["Total", *(format_usd(q.estimated_cost_usd) for q in total.quotes)]
        )
    lines += _table(
        ["Title", *(target.label for target in targets)],
        cost_rows,
        [False, *(True for _ in targets)],
    )

    credit_indexes = [i for i, q in enumerate(total.quotes) if q.credits is not None]
    if credit_indexes:
        lines += [
            "",
            "ELEVENLABS SUBSCRIPTION CREDITS (smallest plan that covers it in one month)",
        ]
        credit_rows = [
            [_clip(r.title), *(_credit_cell(r.comparison.quotes[i]) for i in credit_indexes)]
            for r in reports
        ]
        if many:
            credit_rows.append(
                ["All books in one month", *(_credit_cell(total.quotes[i]) for i in credit_indexes)]
            )
        lines += _table(
            ["Title", *(targets[i].label for i in credit_indexes)],
            credit_rows,
            [False, *(True for _ in credit_indexes)],
        )
        lines += [
            "",
            "ElevenLabs is UNTESTED live in this app. Dollar figures are pay-as-you-go",
            "rates; credits apply to subscription plans. Plan sizes are approximate",
            "(lowest published figure): confirm at https://elevenlabs.io/pricing.",
        ]
    return "\n".join(lines) + "\n"


def run_estimate(source: Path, out: TextIO, err: TextIO) -> int:
    """Estimate one EPUB or a folder of EPUBs. Returns a process exit status."""

    try:
        paths = collect_epubs(source)
    except (OSError, Epub2M4BError) as exc:
        print(f"epub2m4b: {exc}", file=err)
        return 1
    if not paths:
        print(f"epub2m4b: no EPUB files found in {source}", file=err)
        return 1

    reports: list[BookReport] = []
    failed = 0
    for path in paths:
        try:
            reports.append(_report(path))
        except Epub2M4BError as exc:
            failed += 1
            print(f"epub2m4b: skipped {path.name}: {exc}", file=err)
    if reports:
        out.write(render_report(reports))
    return 1 if failed or not reports else 0


__all__ = [
    "BookReport",
    "collect_epubs",
    "format_duration",
    "render_report",
    "run_estimate",
]
