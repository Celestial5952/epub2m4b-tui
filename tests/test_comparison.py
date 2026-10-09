from __future__ import annotations

from decimal import Decimal

import pytest

from epub2m4b.generation.comparison import (
    DEFAULT_TARGETS,
    ProviderQuote,
    QuoteTarget,
    compare_providers,
    describe_quote,
    format_usd,
)
from epub2m4b.models import Chunk, NarrationSettings


def _chunk(text: str, index: int = 0) -> Chunk:
    settings = NarrationSettings("openai", "gpt-4o-mini-tts", "marin", 1.0, "")
    return Chunk.create(chapter_index=0, chunk_index=index, text=text, settings=settings)


# 20,000 words / 100,000 characters: round numbers keep the arithmetic checkable.
_HUNDRED_K = (_chunk("word " * 20_000),)


def test_default_targets_cover_openai_and_both_elevenlabs_price_tiers() -> None:
    comparison = compare_providers(_HUNDRED_K)
    assert [q.target for q in comparison.quotes] == list(DEFAULT_TARGETS)
    assert [q.target.provider for q in comparison.quotes] == ["openai", "elevenlabs", "elevenlabs"]


def test_text_statistics_match_the_existing_openai_job_estimate() -> None:
    comparison = compare_providers(_HUNDRED_K)
    assert comparison.word_count == 20_000
    assert comparison.character_count == 100_000
    # 20,000 words at 120 words per minute.
    assert comparison.estimated_seconds == 10_000


def test_openai_quote_uses_token_pricing_with_safety_margin() -> None:
    openai = compare_providers(_HUNDRED_K).quotes[0]
    # (25,000 text tokens * $0.60 + 200,000 audio tokens * $12) / 1M * 1.15
    assert openai.estimated_cost_usd == Decimal("2.777250")
    assert openai.credits is None
    assert openai.smallest_plan is None
    assert not openai.untested_live


def test_elevenlabs_quotes_report_dollars_credits_and_plan_with_margin() -> None:
    _, multilingual, flash = compare_providers(_HUNDRED_K).quotes
    assert multilingual.estimated_cost_usd == Decimal("11.500000")
    assert multilingual.credits == 115_000
    assert multilingual.smallest_plan == "Pro"
    assert multilingual.untested_live
    # Flash/Turbo bill half the credits per character.
    assert flash.estimated_cost_usd == Decimal("5.750000")
    assert flash.credits == 57_500
    assert flash.smallest_plan == "Creator"
    assert flash.untested_live


def test_quote_beyond_every_plan_is_reported_not_hidden() -> None:
    quote = compare_providers((_chunk("x" * 5_300_000),)).quotes[1]
    assert quote.credits == 6_095_000
    assert quote.smallest_plan is None
    assert quote.exceeds_plans
    assert "more than any plan allows" in describe_quote(quote)


def test_empty_input_prices_at_zero() -> None:
    comparison = compare_providers(())
    assert comparison.character_count == 0
    assert all(q.estimated_cost_usd == 0 for q in comparison.quotes)
    assert comparison.quotes[1].smallest_plan == "Free"


def test_unknown_provider_or_model_is_refused_rather_than_guessed() -> None:
    with pytest.raises(ValueError, match="unknown provider"):
        compare_providers(_HUNDRED_K, [QuoteTarget("acme", "m", "Acme")])
    with pytest.raises(ValueError, match="verified pricing"):
        compare_providers(_HUNDRED_K, [QuoteTarget("openai", "gpt-4o-tts", "Old")])
    with pytest.raises(ValueError, match="verified pricing"):
        compare_providers(_HUNDRED_K, [QuoteTarget("elevenlabs", "eleven_future", "Future")])


def test_custom_targets_and_safety_multiplier_are_honoured() -> None:
    target = QuoteTarget("elevenlabs", "eleven_v3", "ElevenLabs v3")
    quote = compare_providers(_HUNDRED_K, [target], safety_multiplier="1").quotes[0]
    assert quote.credits == 100_000
    assert quote.estimated_cost_usd == Decimal("10.000000")
    # Exactly Creator's allowance: the boundary is inclusive.
    assert quote.smallest_plan == "Creator"


@pytest.mark.parametrize(
    "cost,expected",
    [
        (Decimal("0"), "$0.00"),
        (Decimal("0.001"), "$0.01"),
        (Decimal("2.77725"), "$2.78"),
        (Decimal("11.5"), "$11.50"),
        (Decimal("1234.5"), "$1,234.50"),
    ],
)
def test_format_usd_rounds_up_to_whole_cents(cost: Decimal, expected: str) -> None:
    assert format_usd(cost) == expected


def test_describe_quote_flags_untested_provider_and_names_plan() -> None:
    _, multilingual, _ = compare_providers(_HUNDRED_K).quotes
    assert describe_quote(multilingual) == (
        "ElevenLabs Multilingual v2 (UNTESTED live): $11.50 · 115,000 credits · "
        "smallest plan: Pro"
    )
    assert describe_quote(compare_providers(_HUNDRED_K).quotes[0]) == (
        "OpenAI gpt-4o-mini-tts: $2.78"
    )


def test_exceeds_plans_is_false_without_credits() -> None:
    assert not ProviderQuote(DEFAULT_TARGETS[0], Decimal("1")).exceeds_plans
