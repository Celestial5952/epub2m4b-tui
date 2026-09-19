from __future__ import annotations

from pathlib import Path

import pytest

from epub2m4b.generation.cache import AudioCache
from epub2m4b.models import Chunk, NarrationSettings


def _settings(**changes: object) -> NarrationSettings:
    values: dict[str, object] = {
        "provider": "fake",
        "model": "offline-model",
        "voice": "marin",
        "speed": 1.0,
        "instructions": "Read naturally.",
    }
    values.update(changes)
    return NarrationSettings(**values)  # type: ignore[arg-type]


def _chunk(text: str = "A short sentence.", **changes: object) -> Chunk:
    return Chunk.create(
        chapter_index=0,
        chunk_index=0,
        text=text,
        settings=_settings(**changes),
    )


def test_path_is_deterministic_and_uses_generation_hash_only(tmp_path: Path) -> None:
    cache = AudioCache(tmp_path / "cache")
    chunk = _chunk()

    expected = (
        tmp_path
        / "cache"
        / "narration"
        / chunk.generation_hash[:2]
        / f"{chunk.generation_hash}.wav"
    )
    assert cache.path_for(chunk) == expected
    assert cache.path_for(chunk) == cache.path_for(chunk)
    assert not (tmp_path / "cache").exists()


def test_generation_setting_changes_invalidate_cache_identity() -> None:
    original = _chunk()
    changed = _chunk(voice="cedar")
    assert original.generation_hash != changed.generation_hash


def test_constructor_has_no_side_effects_and_ensure_creates_namespaces(
    tmp_path: Path,
) -> None:
    root = tmp_path / "not-created-yet"
    cache = AudioCache(root)
    assert not root.exists()

    assert cache.ensure() is cache
    assert (root / "narration").is_dir()
    assert (root / "previews").is_dir()


def test_preview_namespace_is_separate_from_narration(tmp_path: Path) -> None:
    cache = AudioCache(tmp_path / "cache").ensure()
    assert cache.preview_root == tmp_path / "cache" / "previews"
    assert cache.preview_root != cache.narration_root
    assert cache.path_for(_chunk()).parent.parent == cache.narration_root


def test_lookup_returns_nonempty_validated_regular_file(tmp_path: Path) -> None:
    cache = AudioCache(tmp_path / "cache")
    chunk = _chunk()
    path = cache.path_for(chunk)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"WAV")

    seen: list[Path] = []

    def validator(candidate: Path) -> bool:
        seen.append(candidate)
        return candidate.read_bytes() == b"WAV"

    assert cache.lookup(chunk, validator) == path
    assert seen == [path]


def test_lookup_misses_missing_empty_directory_and_validator_false(tmp_path: Path) -> None:
    cache = AudioCache(tmp_path / "cache")
    chunk = _chunk()
    path = cache.path_for(chunk)

    assert cache.lookup(chunk, lambda _: True) is None
    path.parent.mkdir(parents=True)
    path.touch()
    assert cache.lookup(chunk, lambda _: True) is None
    path.unlink()
    path.mkdir()
    assert cache.lookup(chunk, lambda _: True) is None
    path.rmdir()
    path.write_bytes(b"audio")
    assert cache.lookup(chunk, lambda _: False) is None
    assert path.exists()


def test_lookup_treats_validator_exception_as_miss_without_deleting_file(
    tmp_path: Path,
) -> None:
    cache = AudioCache(tmp_path / "cache")
    chunk = _chunk()
    path = cache.path_for(chunk)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"audio")

    def broken_validator(_: Path) -> bool:
        raise RuntimeError("not valid")

    assert cache.lookup(chunk, broken_validator) is None
    assert path.read_bytes() == b"audio"


def test_lookup_rejects_symlinked_audio(tmp_path: Path) -> None:
    cache = AudioCache(tmp_path / "cache")
    chunk = _chunk()
    path = cache.path_for(chunk)
    path.parent.mkdir(parents=True)
    target = tmp_path / "real.wav"
    target.write_bytes(b"audio")
    path.symlink_to(target)

    assert cache.lookup(chunk, lambda _: True) is None
    assert path.is_symlink()


@pytest.mark.parametrize("value", ["", "A" * 64, "g" * 64, "0" * 63, "0" * 65])
def test_path_for_rejects_invalid_generation_hash(tmp_path: Path, value: str) -> None:
    chunk = _chunk()
    invalid = Chunk(
        chapter_index=chunk.chapter_index,
        chunk_index=chunk.chunk_index,
        text=chunk.text,
        text_hash=chunk.text_hash,
        generation_hash=value,
    )
    with pytest.raises(ValueError, match="generation hash"):
        AudioCache(tmp_path / "cache").path_for(invalid)


def test_unicode_and_spaces_in_root_are_supported(tmp_path: Path) -> None:
    root = tmp_path / "音声 cache with spaces"
    cache = AudioCache(root).ensure()
    path = cache.path_for(_chunk())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("音声".encode())
    assert cache.lookup(_chunk(), lambda candidate: candidate.stat().st_size > 0) == path
