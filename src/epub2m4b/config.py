from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from pathlib import Path

DEFAULT_INSTRUCTIONS = """Narrate this as a professional audiobook narrator.

Speak clearly and naturally at a comfortable listening pace.
Maintain consistent voice, tone, accent, volume, and pacing.
Use natural pauses at sentence and paragraph boundaries.
Give dialogue subtle emotional expression without becoming theatrical.
Do not add commentary, explanations, sound effects, or words not present
in the source text."""

# This model was shipped by an early EPUB2M4B release but OpenAI now rejects it
# for the affected projects. Keep the migration deliberately narrow: users may
# still configure other valid model IDs outside the Settings menu.
RETIRED_OPENAI_MODELS = frozenset({"gpt-4o-tts"})
DEFAULT_OPENAI_MODEL = "gpt-4o-mini-tts"

_CREDENTIAL_TERMS = (
    "apikey",
    "authorization",
    "credential",
    "header",
    "password",
    "secret",
    "token",
)


def _looks_like_credential(name: str) -> bool:
    normalized = "".join(character for character in name.casefold() if character.isalnum())
    return any(term in normalized for term in _CREDENTIAL_TERMS)


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Non-secret user configuration.

    API credentials deliberately do not belong in this schema.
    """

    onboarding_complete: bool = False
    provider: str = "openai"
    model: str = DEFAULT_OPENAI_MODEL
    voice: str = "marin"
    speed: float = 1.0
    instructions: str = DEFAULT_INSTRUCTIONS
    cache_directory: Path | None = None
    book_directory: Path | None = None
    output_directory: Path | None = None
    work_directory: Path | None = None
    concurrency: int = 2
    aac_bitrate_kbps: int = 96
    maximum_estimated_cost_usd: float = 25.0
    generation_options: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.onboarding_complete, bool):
            raise ValueError("onboarding completion must be a boolean")
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("provider is required")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("model is required")
        if not isinstance(self.voice, str) or not self.voice.strip():
            raise ValueError("voice is required")
        if not isinstance(self.instructions, str):
            raise ValueError("instructions must be a string")
        if (
            isinstance(self.speed, bool)
            or not isinstance(self.speed, (int, float))
            or not math.isfinite(self.speed)
            or self.speed <= 0
        ):
            raise ValueError("speed must be a finite number greater than zero")
        if (
            isinstance(self.concurrency, bool)
            or not isinstance(self.concurrency, int)
            or not 1 <= self.concurrency <= 16
        ):
            raise ValueError("concurrency must be between 1 and 16")
        if (
            isinstance(self.aac_bitrate_kbps, bool)
            or not isinstance(self.aac_bitrate_kbps, int)
            or self.aac_bitrate_kbps <= 0
        ):
            raise ValueError("AAC bitrate must be greater than zero")
        if (
            isinstance(self.maximum_estimated_cost_usd, bool)
            or not isinstance(self.maximum_estimated_cost_usd, (int, float))
            or not math.isfinite(self.maximum_estimated_cost_usd)
            or self.maximum_estimated_cost_usd < 0
        ):
            raise ValueError("maximum estimated cost must be a finite non-negative number")
        if self.output_directory is not None and not isinstance(self.output_directory, Path):
            raise ValueError("output directory must be a path")
        if self.cache_directory is not None and not isinstance(self.cache_directory, Path):
            raise ValueError("cache directory must be a path")
        if self.book_directory is not None and not isinstance(self.book_directory, Path):
            raise ValueError("book directory must be a path")
        if self.work_directory is not None and not isinstance(self.work_directory, Path):
            raise ValueError("work directory must be a path")
        if not isinstance(self.generation_options, dict):
            raise ValueError("generation options must be a dictionary")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.generation_options.items()
        ):
            raise ValueError("generation options must contain string keys and values")
        if any(_looks_like_credential(key) for key in self.generation_options):
            raise ValueError("generation options must not contain credentials")


def migrate_retired_openai_model(config: AppConfig) -> AppConfig:
    """Replace only the known retired OpenAI model in legacy configuration."""

    if config.provider == "openai" and config.model in RETIRED_OPENAI_MODELS:
        return replace(config, model=DEFAULT_OPENAI_MODEL)
    return config
