"""Conservative, provider-independent narration cost estimates."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from epub2m4b.models import Chunk

_WORDS = re.compile(r"\S+")
_MILLION = Decimal("1000000")


def _decimal(value: object, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise ValueError(f"{name} must be finite and positive") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return result


def _ceiling(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


@dataclass(frozen=True, slots=True)
class TTSPricing:
    text_input_usd_per_million_tokens: Decimal | int | float | str
    audio_output_usd_per_million_tokens: Decimal | int | float | str
    audio_tokens_per_second: Decimal | int | float | str

    def __post_init__(self) -> None:
        for name in (
            "text_input_usd_per_million_tokens",
            "audio_output_usd_per_million_tokens",
            "audio_tokens_per_second",
        ):
            object.__setattr__(self, name, _decimal(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class NarrationEstimate:
    word_count: int
    character_count: int
    estimated_seconds: int
    estimated_minutes: Decimal
    text_input_tokens: int
    audio_output_tokens: int
    estimated_cost_usd: Decimal

    @property
    def total_cost_usd(self) -> Decimal:
        return self.estimated_cost_usd


def estimate_narration(
    chunks: Iterable[Chunk],
    pricing: TTSPricing,
    words_per_minute: int | float | Decimal,
    safety_multiplier: int | float | Decimal = 1.15,
    text_chars_per_token: int | float | Decimal = 4,
) -> NarrationEstimate:
    """Estimate duration and spend using conservative ceiling arithmetic."""

    wpm = _decimal(words_per_minute, "words_per_minute")
    safety = _decimal(safety_multiplier, "safety_multiplier")
    chars_per_token = _decimal(text_chars_per_token, "text_chars_per_token")
    if not isinstance(pricing, TTSPricing):
        raise TypeError("pricing must be TTSPricing")

    chunk_list = tuple(chunks)
    character_count = sum(len(chunk.text) for chunk in chunk_list)
    word_count = sum(len(_WORDS.findall(chunk.text)) for chunk in chunk_list)
    seconds = _ceiling(Decimal(word_count) * Decimal("60") / wpm)
    text_tokens = _ceiling(Decimal(character_count) / chars_per_token)
    audio_tokens = _ceiling(Decimal(seconds) * pricing.audio_tokens_per_second)

    base_cost = (
        Decimal(text_tokens) * pricing.text_input_usd_per_million_tokens / _MILLION
        + Decimal(audio_tokens) * pricing.audio_output_usd_per_million_tokens / _MILLION
    )
    cost = base_cost * safety
    # Round upward to the smallest micro-dollar so a cap comparison never
    # underestimates a fractional Decimal result.
    cost = cost.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
    return NarrationEstimate(
        word_count=word_count,
        character_count=character_count,
        estimated_seconds=seconds,
        estimated_minutes=Decimal(seconds) / Decimal("60"),
        text_input_tokens=text_tokens,
        audio_output_tokens=audio_tokens,
        estimated_cost_usd=cost,
    )
