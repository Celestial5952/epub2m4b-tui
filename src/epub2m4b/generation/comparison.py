"""Offline side-by-side narration estimates across supported providers.

Everything here is pure arithmetic over already-prepared chunks. It never reads a
credential, opens a network connection, or authorizes paid work, so it is safe to
show for any provider, including ones still marked UNTESTED live.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from epub2m4b.generation.elevenlabs_estimate import (
    estimate_elevenlabs_cost,
    estimate_elevenlabs_credits,
    smallest_elevenlabs_plan,
)
from epub2m4b.generation.estimate import (
    DEFAULT_SAFETY_MULTIPLIER,
    DEFAULT_WORDS_PER_MINUTE,
    OPENAI_TTS_PRICING,
    estimate_narration,
)
from epub2m4b.models import Chunk

_OPENAI_PRICED_MODEL = "gpt-4o-mini-tts"


@dataclass(frozen=True, slots=True)
class QuoteTarget:
    """One provider/model pairing to price."""

    provider: str
    model: str
    label: str


DEFAULT_TARGETS: tuple[QuoteTarget, ...] = (
    QuoteTarget("openai", _OPENAI_PRICED_MODEL, "OpenAI gpt-4o-mini-tts"),
    QuoteTarget("elevenlabs", "eleven_multilingual_v2", "ElevenLabs Multilingual v2"),
    QuoteTarget("elevenlabs", "eleven_flash_v2_5", "ElevenLabs Flash v2.5"),
)


@dataclass(frozen=True, slots=True)
class ProviderQuote:
    """Estimated spend for one target, including the safety margin."""

    target: QuoteTarget
    estimated_cost_usd: Decimal
    #: ElevenLabs subscription credits (with margin); ``None`` for per-token providers.
    credits: int | None = None
    #: Smallest ElevenLabs plan covering ``credits`` in one month, if any does.
    smallest_plan: str | None = None
    #: True while the provider has not passed an authorized live verification.
    untested_live: bool = False

    @property
    def exceeds_plans(self) -> bool:
        return self.credits is not None and self.smallest_plan is None


@dataclass(frozen=True, slots=True)
class ProviderComparison:
    """Text size plus a quote for every requested target."""

    word_count: int
    character_count: int
    estimated_seconds: int
    quotes: tuple[ProviderQuote, ...]


def format_usd(cost: Decimal) -> str:
    """Round up to whole cents so a displayed price never understates the estimate."""

    return f"${cost.quantize(Decimal('0.01'), rounding=ROUND_CEILING):,}"


def describe_quote(quote: ProviderQuote) -> str:
    """One human-readable line for a quote."""

    label = quote.target.label + (" (UNTESTED live)" if quote.untested_live else "")
    text = f"{label}: {format_usd(quote.estimated_cost_usd)}"
    if quote.credits is not None:
        plan = (
            f"smallest plan: {quote.smallest_plan}"
            if quote.smallest_plan is not None
            else "more than any plan allows in one month"
        )
        text += f" · {quote.credits:,} credits · {plan}"
    return text


def compare_providers(
    chunks: Iterable[Chunk],
    targets: Iterable[QuoteTarget] = DEFAULT_TARGETS,
    *,
    safety_multiplier: Decimal | int | float | str = DEFAULT_SAFETY_MULTIPLIER,
) -> ProviderComparison:
    """Price ``chunks`` for each target without any network or credential access."""

    chunk_list = tuple(chunks)
    base = estimate_narration(
        chunk_list,
        OPENAI_TTS_PRICING,
        DEFAULT_WORDS_PER_MINUTE,
        safety_multiplier=safety_multiplier,
    )
    quotes: list[ProviderQuote] = []
    for target in targets:
        if target.provider == "openai":
            if target.model != _OPENAI_PRICED_MODEL:
                raise ValueError("OpenAI model does not have verified pricing")
            quotes.append(ProviderQuote(target, base.estimated_cost_usd))
        elif target.provider == "elevenlabs":
            cost = estimate_elevenlabs_cost(
                chunk_list, target.model, safety_multiplier=safety_multiplier
            )
            credits = estimate_elevenlabs_credits(
                chunk_list, target.model, safety_multiplier=safety_multiplier
            )
            quotes.append(
                ProviderQuote(
                    target,
                    cost.estimated_cost_usd,
                    credits=credits,
                    smallest_plan=smallest_elevenlabs_plan(credits),
                    untested_live=True,
                )
            )
        else:
            raise ValueError(f"unknown provider: {target.provider!r}")
    return ProviderComparison(
        word_count=base.word_count,
        character_count=base.character_count,
        estimated_seconds=base.estimated_seconds,
        quotes=tuple(quotes),
    )


__all__ = [
    "DEFAULT_TARGETS",
    "ProviderComparison",
    "ProviderQuote",
    "QuoteTarget",
    "compare_providers",
    "describe_quote",
    "format_usd",
]
