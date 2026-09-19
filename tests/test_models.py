from dataclasses import replace

import pytest

from epub2m4b.models import Chunk, NarrationSettings, generation_hash


def settings(**changes: object) -> NarrationSettings:
    base = NarrationSettings(
        provider="openai",
        model="gpt-4o-mini-tts",
        voice="marin",
        speed=1.0,
        instructions="Read naturally.",
    )
    return replace(base, **changes)


def test_generation_hash_is_deterministic() -> None:
    first = settings(generation_options={"alpha": "1", "beta": "2"})
    second = settings(generation_options={"beta": "2", "alpha": "1"})

    assert generation_hash("Same text", first) == generation_hash("Same text", second)


def test_generation_hash_changes_for_narration_inputs() -> None:
    original = generation_hash("Same text", settings())

    assert generation_hash("Changed text", settings()) != original
    assert generation_hash("Same text", settings(voice="coral")) != original
    assert generation_hash("Same text", settings(speed=1.1)) != original
    assert generation_hash("Same text", settings(model="other-model")) != original
    assert generation_hash("Same text", settings(instructions="Different.")) != original


def test_chunk_id_is_stable_and_human_readable() -> None:
    chunk = Chunk.create(
        chapter_index=7,
        chunk_index=3,
        text="A deterministic passage.",
        settings=settings(),
    )

    assert chunk.id.startswith("chapter-008_chunk-004_")
    assert len(chunk.id.rsplit("_", 1)[1]) == 12


@pytest.mark.parametrize("name", ["api_key", "API-Key", "authorization", "extra_headers"])
def test_narration_settings_reject_credential_options(name: str) -> None:
    with pytest.raises(ValueError, match="credentials"):
        settings(generation_options={name: "must-not-be-stored"})


@pytest.mark.parametrize("speed", [0, -0.5, float("nan"), float("inf"), float("-inf"), True, False])
def test_narration_settings_reject_invalid_speed(speed: float) -> None:
    with pytest.raises(ValueError, match="speed"):
        settings(speed=speed)

