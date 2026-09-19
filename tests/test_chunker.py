from __future__ import annotations

import pytest

from epub2m4b.generation.chunker import chunk_text
from epub2m4b.models import NarrationSettings


@pytest.fixture
def settings() -> NarrationSettings:
    return NarrationSettings("fake", "model-a", "alloy", 1.0, "")


def pieces(text: str, settings: NarrationSettings, **kwargs: int) -> list[str]:
    return [chunk.text for chunk in chunk_text(text, chapter_index=2, settings=settings, **kwargs)]


def test_empty_small_exact_and_ceiling(settings: NarrationSettings) -> None:
    assert pieces(" \n\t", settings) == []
    assert pieces("hello", settings, target_chars=3, max_chars=5) == ["hello"]
    assert [
        len(value) for value in pieces("12345 67890", settings, target_chars=5, max_chars=5)
    ] == [5, 5]
    with pytest.raises(ValueError):
        chunk_text("x", chapter_index=0, settings=settings, max_chars=4001)


def test_scene_and_paragraph_boundaries(settings: NarrationSettings) -> None:
    result = pieces("one two\n\n* * *\n\nthree four five", settings, target_chars=8, max_chars=20)
    assert result[0] == "one two\n\n* * *"


def test_sentence_boundary(settings: NarrationSettings) -> None:
    result = pieces("one two. three four five six", settings, target_chars=8, max_chars=20)
    assert result[0] == "one two."


@pytest.mark.parametrize("mark", [",", ";", ":", "—", "–"])
def test_punctuation_boundaries(settings: NarrationSettings, mark: str) -> None:
    result = pieces(f"one two{mark} three four five six", settings, target_chars=8, max_chars=20)
    assert result[0].endswith(mark)


def test_ellipsis_and_whitespace_boundaries(settings: NarrationSettings) -> None:
    assert pieces("one two… three four five", settings, target_chars=8, max_chars=20)[0].endswith(
        "…"
    )
    assert pieces("one two three four five", settings, target_chars=8, max_chars=20)[0] == "one two"


def test_useful_threshold_prefers_lower_quality_over_tiny_scene(
    settings: NarrationSettings,
) -> None:
    result = pieces("A\n\n* * *\n\n" + "word " * 8, settings, target_chars=12, max_chars=30)
    assert len(result[0]) >= 6
    assert not result[0].endswith("A")


def test_hard_split_only_for_word_without_whitespace(settings: NarrationSettings) -> None:
    result = pieces("x" * 25, settings, target_chars=8, max_chars=10)
    assert [len(value) for value in result] == [10, 10, 5]
    assert pieces("word " * 8, settings, target_chars=8, max_chars=10)


def test_no_empty_chunks_or_loss_of_non_whitespace(settings: NarrationSettings) -> None:
    value = "  A   B\n\n\n C   D  "
    result = pieces(value, settings, target_chars=2, max_chars=4)
    assert all(result)
    assert "".join("".join(result).split()) == "".join(value.split())


def test_unicode_limits_and_identity_are_deterministic(settings: NarrationSettings) -> None:
    value = "😀 café — naïve… " * 20
    first = chunk_text(value, chapter_index=2, settings=settings, target_chars=20, max_chars=30)
    second = chunk_text(value, chapter_index=2, settings=settings, target_chars=20, max_chars=30)
    assert first == second
    assert all(len(chunk.text) <= 30 for chunk in first)
    assert [chunk.chunk_index for chunk in first] == list(range(len(first)))


def test_identity_changes_with_text_and_settings(settings: NarrationSettings) -> None:
    original = chunk_text("same text", chapter_index=0, settings=settings)[0]
    assert (
        original.generation_hash
        != chunk_text("other text", chapter_index=0, settings=settings)[0].generation_hash
    )
    for field, value in [
        ("voice", "nova"),
        ("model", "model-b"),
        ("speed", 1.1),
        ("instructions", "calm"),
    ]:
        values = {
            "provider": "fake",
            "model": "model-a",
            "voice": "alloy",
            "speed": 1.0,
            "instructions": "",
        }
        values[field] = value
        changed = NarrationSettings(**values)
        assert (
            original.generation_hash
            != chunk_text("same text", chapter_index=0, settings=changed)[0].generation_hash
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"chapter_index": -1},
        {"target_chars": 0},
        {"max_chars": 0},
        {"target_chars": 5, "max_chars": 4},
        {"target_chars": 4, "max_chars": 4001},
    ],
)
def test_invalid_inputs(settings: NarrationSettings, kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        call_kwargs = {"chapter_index": 0, **kwargs}
        chunk_text("text", settings=settings, **call_kwargs)
