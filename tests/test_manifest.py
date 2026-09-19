import json
from pathlib import Path

import pytest

from epub2m4b.exceptions import ManifestError, UnsupportedManifestVersionError
from epub2m4b.generation.manifest import ManifestRepository
from epub2m4b.models import (
    Chunk,
    JobManifest,
    JobStatus,
    ManifestBook,
    ManifestSource,
    NarrationSettings,
)


def manifest() -> JobManifest:
    settings = NarrationSettings("openai", "model", "voice", 1.0, "Read", {"x": 1})
    return JobManifest(
        "job",
        "1.0",
        ManifestSource("book.epub", "abc"),
        ManifestBook("Book", ("A",)),
        settings,
        (
            Chunk.create(
                chapter_index=0,
                chunk_index=0,
                text="Hello",
                settings=settings,
            ),
        ),
        status=JobStatus.COMPLETE,
        created_at="now",
        updated_at="later",
    )


def test_round_trip_and_deterministic_bytes(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "manifest.json"
    ManifestRepository.save(path, manifest())
    first = path.read_bytes()
    assert ManifestRepository.load(path) == manifest()
    ManifestRepository.save(path, manifest())
    assert path.read_bytes() == first


def test_rejects_bad_json_and_missing_fields(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ManifestError):
        ManifestRepository.load(path)
    path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    with pytest.raises(ManifestError):
        ManifestRepository.load(path)


def test_rejects_unsupported_version(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    with pytest.raises(UnsupportedManifestVersionError):
        ManifestRepository.load(path)


def test_replace_failure_preserves_old_file_and_removes_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(b"old")

    def fail_replace(source: str, destination: Path) -> None:
        raise OSError("simulated failure")

    monkeypatch.setattr("epub2m4b.generation.manifest.os.replace", fail_replace)
    with pytest.raises(OSError):
        ManifestRepository.save(path, manifest())
    assert path.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [path]


def test_save_rejects_credentials_added_after_settings_creation(tmp_path: Path) -> None:
    value = manifest()
    value.narration.generation_options["API-Key"] = "must-not-be-written"
    path = tmp_path / "manifest.json"

    with pytest.raises(ManifestError, match="credentials"):
        ManifestRepository.save(path, value)

    assert not path.exists()
