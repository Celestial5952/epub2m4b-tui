"""Conservative cash-cost estimates for supported ElevenLabs TTS models."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation

from epub2m4b.models import Chunk

_THOUSAND = Decimal("1000")
_MICRO_DOLLAR = Decimal("0.000001")
_MODEL_RATES_USD_PER_THOUSAND = {
    "eleven_flash_v2": Decimal("0.05"),
    "eleven_flash_v2_5": Decimal("0.05"),
    "eleven_turbo_v2": Decimal("0.05"),
    "eleven_turbo_v2_5": Decimal("0.05"),
    "eleven_multilingual_v2": Decimal("0.10"),
    "eleven_v3": Decimal("0.10"),
}


def _positive_decimal(value: object, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{name} must be finite and positive") from None
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return result


@dataclass(frozen=True, slots=True)
class ElevenLabsCostEstimate:
    character_count: int
    usd_per_thousand_characters: Decimal
    safety_multiplier: Decimal
    estimated_cost_usd: Decimal


def estimate_elevenlabs_cost(
    chunks: Iterable[Chunk],
    model_id: str,
    *,
    safety_multiplier: Decimal | int | float | str = "1.15",
    voice_has_custom_rate: bool = False,
) -> ElevenLabsCostEstimate:
    """Return a PAYG upper estimate or refuse pricing that cannot be bounded."""

    if not isinstance(model_id, str) or model_id not in _MODEL_RATES_USD_PER_THOUSAND:
        raise ValueError("ElevenLabs model does not have verified pricing")
    if not isinstance(voice_has_custom_rate, bool):
        raise ValueError("custom voice rate flag must be a boolean")
    if voice_has_custom_rate:
        raise ValueError("ElevenLabs custom-rate voices require an explicit price")
    safety = _positive_decimal(safety_multiplier, "safety multiplier")
    character_count = sum(len(chunk.text) for chunk in chunks)
    rate = _MODEL_RATES_USD_PER_THOUSAND[model_id]
    cost = Decimal(character_count) * rate / _THOUSAND * safety
    return ElevenLabsCostEstimate(
        character_count=character_count,
        usd_per_thousand_characters=rate,
        safety_multiplier=safety,
        estimated_cost_usd=cost.quantize(_MICRO_DOLLAR, rounding=ROUND_CEILING),
    )


__all__ = ["ElevenLabsCostEstimate", "estimate_elevenlabs_cost"]
