from decimal import Decimal

import pytest

from epub2m4b.generation.estimate import TTSPricing, estimate_narration
from epub2m4b.models import Chunk, NarrationSettings


def _chunks() -> tuple[Chunk, ...]:
    settings = NarrationSettings("fake", "model", "voice", 1.0, "")
    return (Chunk.create(chapter_index=0, chunk_index=0, text="one two three", settings=settings),)


def test_estimate_uses_conservative_ceilings_and_decimal_cost() -> None:
    pricing = TTSPricing("1", "2", "1.5")
    result = estimate_narration(
        _chunks(), pricing, 2, safety_multiplier="1.15", text_chars_per_token=4
    )
    assert result.word_count == 3
    assert result.character_count == 13
    assert result.estimated_seconds == 90
    assert result.text_input_tokens == 4
    assert result.audio_output_tokens == 135
    assert result.estimated_cost_usd == Decimal("0.000316")


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_estimate_rejects_non_positive_or_non_finite_inputs(value: object) -> None:
    pricing = TTSPricing("1", "1", "1")
    with pytest.raises(ValueError):
        estimate_narration(_chunks(), pricing, value)  # type: ignore[arg-type]


def test_pricing_is_explicit_and_validated() -> None:
    with pytest.raises(ValueError):
        TTSPricing("nan", "1", "1")
