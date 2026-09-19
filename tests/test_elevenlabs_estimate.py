from decimal import Decimal

import pytest

from epub2m4b.generation.elevenlabs_estimate import estimate_elevenlabs_cost
from epub2m4b.models import Chunk, NarrationSettings


def _chunk(text: str, index: int = 0) -> Chunk:
    settings = NarrationSettings(
        "elevenlabs", "eleven_multilingual_v2", "voice-id", 1.0, ""
    )
    return Chunk.create(
        chapter_index=0,
        chunk_index=index,
        text=text,
        settings=settings,
    )


@pytest.mark.parametrize(
    "model,expected_rate,expected_cost",
    [
        ("eleven_multilingual_v2", "0.10", "0.287500"),
        ("eleven_v3", "0.10", "0.287500"),
        ("eleven_flash_v2", "0.05", "0.143750"),
        ("eleven_flash_v2_5", "0.05", "0.143750"),
        ("eleven_turbo_v2", "0.05", "0.143750"),
        ("eleven_turbo_v2_5", "0.05", "0.143750"),
    ],
)
def test_verified_model_rates_are_conservative(
    model: str, expected_rate: str, expected_cost: str
) -> None:
    estimate = estimate_elevenlabs_cost([_chunk("x" * 2_500)], model)
    assert estimate.character_count == 2_500
    assert estimate.usd_per_thousand_characters == Decimal(expected_rate)
    assert estimate.safety_multiplier == Decimal("1.15")
    assert estimate.estimated_cost_usd == Decimal(expected_cost)


def test_multiple_chunks_and_upward_rounding() -> None:
    estimate = estimate_elevenlabs_cost(
        [_chunk("a", 0), _chunk("bc", 1)],
        "eleven_multilingual_v2",
        safety_multiplier="1.01",
    )
    assert estimate.character_count == 3
    assert estimate.estimated_cost_usd == Decimal("0.000303")


@pytest.mark.parametrize("model", ["", "future-model", None])
def test_unknown_models_are_blocked_instead_of_guessed(model: str | None) -> None:
    with pytest.raises(ValueError, match="verified pricing"):
        estimate_elevenlabs_cost([_chunk("text")], model)  # type: ignore[arg-type]


def test_custom_rate_voice_is_blocked_without_explicit_price() -> None:
    with pytest.raises(ValueError, match="custom-rate"):
        estimate_elevenlabs_cost(
            [_chunk("text")],
            "eleven_multilingual_v2",
            voice_has_custom_rate=True,
        )


@pytest.mark.parametrize("value", [0, -1, "nan", "inf", None])
def test_safety_multiplier_must_be_positive_and_finite(value: object) -> None:
    with pytest.raises(ValueError, match="safety multiplier"):
        estimate_elevenlabs_cost(
            [_chunk("text")],
            "eleven_multilingual_v2",
            safety_multiplier=value,  # type: ignore[arg-type]
        )


def test_iterable_is_consumed_once() -> None:
    chunks = (_chunk(text, index) for index, text in enumerate(("one", "two")))
    estimate = estimate_elevenlabs_cost(chunks, "eleven_multilingual_v2")
    assert estimate.character_count == 6
