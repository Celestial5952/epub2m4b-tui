"""Deterministic, boundary-aware chunking for narration requests."""

from __future__ import annotations

import re

from epub2m4b.generation.normalize import normalize_text
from epub2m4b.models import Chunk, NarrationSettings

# A candidate is useful when it is not so close to the beginning that it would
# create a pathological fragment.  This fixed half-target rule is deliberately
# part of the algorithm: it keeps output stable while allowing a lower-quality
# boundary near the target to beat a tiny high-quality fragment.
_MIN_USEFUL_RATIO = 0.5
_SCENE = re.compile(r"(?:\*[ \t]*){2,}|(?:[·•][ \t]*){2,}|(?:[-—–][ \t]*){2,}")
_SENTENCE_END = re.compile(r"[.!?…](?:[\"'’”»)\]]*)")


def _scene_positions(text: str, start: int, limit: int) -> set[int]:
    positions: set[int] = set()
    for match in _SCENE.finditer(text, start, limit):
        # Scene markers are normally on their own line.  Requiring a line
        # boundary avoids treating ordinary runs of punctuation as a break.
        before = text[match.start() - 1] if match.start() else "\n"
        after = text[match.end()] if match.end() < len(text) else "\n"
        if before == "\n" and after in "\n ":
            positions.add(match.end())
    return positions


def _candidates(text: str, start: int, limit: int) -> dict[int, int]:
    """Return cut positions and quality (lower quality number is preferred)."""

    candidates: dict[int, int] = {}
    for position in _scene_positions(text, start, limit):
        candidates[position] = 0

    # Paragraphs are represented by the first newline of a blank-line run.
    for match in re.finditer(r"\n[ \t]*\n[ \t]*", text[start:limit]):
        position = start + match.start()
        candidates[position] = min(candidates.get(position, 99), 1)

    for match in _SENTENCE_END.finditer(text, start, limit):
        position = match.end()
        if position < len(text) and text[position].isspace():
            candidates[position] = min(candidates.get(position, 99), 2)

    # Punctuation followed by whitespace is useful when a chapter has long,
    # sentence-heavy paragraphs.  Sentence candidates remain higher quality.
    for position in range(start + 1, limit):
        if text[position].isspace() and text[position - 1] in ",;:—–":
            candidates[position] = min(candidates.get(position, 99), 3)

    # Any whitespace is a safe word boundary.  Run starts avoid emitting
    # whitespace-only chunks and leave boundary whitespace to trimming.
    position = start
    while position < limit:
        if text[position].isspace() and (position == start or not text[position - 1].isspace()):
            candidates[position] = min(candidates.get(position, 99), 4)
        position += 1
    return {position: quality for position, quality in candidates.items() if position > start}


def _choose_cut(text: str, start: int, target: int, maximum: int) -> int:
    # Never manufacture a short trailing chunk when the remainder already
    # fits.  This also makes exact-limit and whitespace-run inputs intuitive.
    if len(text) - start <= maximum:
        return len(text)
    limit = min(len(text), start + maximum)
    candidates = _candidates(text, start, limit)
    if not candidates:
        return limit

    useful_floor = start + max(1, int(target * _MIN_USEFUL_RATIO))
    useful = [
        (position, quality) for position, quality in candidates.items() if position >= useful_floor
    ]
    pool = useful or list(candidates.items())
    # Quality is strict among useful boundaries; distance breaks ties.  This
    # makes paragraph/scene boundaries win without accepting tiny fragments.
    best_quality = min(quality for _, quality in pool)
    quality_pool = [(position, quality) for position, quality in pool if quality == best_quality]
    return min(quality_pool, key=lambda item: (abs(item[0] - (start + target)), -item[0]))[0]


def chunk_text(
    text: str,
    *,
    chapter_index: int,
    settings: NarrationSettings,
    target_chars: int = 3200,
    max_chars: int = 4000,
) -> tuple[Chunk, ...]:
    """Normalize and split chapter prose into stable TTS-safe chunks."""

    if chapter_index < 0:
        raise ValueError("chapter index cannot be negative")
    if target_chars <= 0 or max_chars <= 0:
        raise ValueError("chunk limits must be positive")
    if target_chars > max_chars:
        raise ValueError("target cannot exceed maximum")
    if max_chars > 4000:
        raise ValueError("maximum chunk size cannot exceed 4000")

    normalized = normalize_text(text)
    if not normalized:
        return ()

    chunks: list[Chunk] = []
    start = 0
    while start < len(normalized):
        cut = _choose_cut(normalized, start, target_chars, max_chars)
        piece = normalized[start:cut].strip()
        if not piece:
            # Only consume boundary whitespace.  In particular, never skip a
            # substantive character if a future change introduces a cut at a
            # whitespace run's edge.
            start = cut
            while start < len(normalized) and normalized[start].isspace():
                start += 1
            continue
        chunks.append(
            Chunk.create(
                chapter_index=chapter_index,
                chunk_index=len(chunks),
                text=piece,
                settings=settings,
            )
        )
        start = cut
        while start < len(normalized) and normalized[start].isspace():
            start += 1
    return tuple(chunks)
