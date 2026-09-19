"""Deterministic Unicode and whitespace normalization for narration."""

from __future__ import annotations

import re
import unicodedata

_REMOVED = frozenset(
    {
        "\u00ad",  # soft hyphen
        "\u200b",
        "\u200c",
        "\u200d",
        "\u200e",
        "\u200f",  # zero-width marks
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",  # bidi formatting
        "\u2060",
        "\u2061",
        "\u2062",
        "\u2063",
        "\u2064",
        "\u2065",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
        "\ufeff",
    }
)
_MANY_NEWLINES = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """Normalize Unicode, line endings, and whitespace without rewriting prose."""

    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u2028", "\n").replace("\u2029", "\n")
    text = "".join(char for char in text if char not in _REMOVED)

    # Convert horizontal Unicode whitespace (including NBSP) to a plain space,
    # leaving paragraph/newline structure intact.
    text = "".join(" " if char != "\n" and char.isspace() else char for char in text)
    text = "\n".join(line.strip(" ") for line in text.split("\n"))
    text = _MANY_NEWLINES.sub("\n\n", text)
    return text.strip(" \n")
