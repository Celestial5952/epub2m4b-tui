from __future__ import annotations

from pathlib import Path

import pytest

from epub2m4b.app.jobs import JobStore
from epub2m4b.generation.manifest import ManifestRepository
from epub2m4b.models import (
    Chunk,
    ChunkStatus,
    JobManifest,
    JobStatus,
    ManifestBook,
    ManifestSource,
    NarrationSettings,
)


def _manifest(job_id: str, stamp: str | None, complete: int = 0) -> JobManifest:
    settings = NarrationSettings("fake", "model", "voice", 1.0, "")
    chunks = tuple(
        Chunk.create(chapter_index=0, chunk_index=i, text=f"text {i}", settings=settings)
        if i >= complete
        else Chunk(
            chapter_index=0,
            chunk_index=i,
            text=f"text {i}",
            text_hash="a" * 64,
            generation_hash=f"{i + 1:064x}",
            status=ChunkStatus.COMPLETE,
        )
        for i in range(3)
    )
    return JobManifest(
        job_id=job_id,
        app_version="test",
        source=ManifestSource("book.epub", "b" * 64),
        book=ManifestBook("Title", ("Author",)),
        narration=settings,
        chunks=chunks,
        status=JobStatus.RUNNING,
        updated_at=stamp,
    )


def _write(root: Path, job_id: str, stamp: str | None, complete: int = 0) -> Path:
    directory = root / job_id
    ManifestRepository.save(directory / "manifest.json", _manifest(job_id, stamp, complete))
    return directory


def test_constructor_and_list_have_no_writes(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    store = JobStore(root)
    assert store.list() == ()
    assert not root.exists()


def test_ensure_creates_root_and_returns_self(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    assert store.ensure() is store
    assert store.root.is_dir()


def test_safe_ids_and_manifest_path(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    assert store.manifest_path("book-1") == tmp_path / "book-1" / "manifest.json"
    for unsafe in ("", "../x", "/tmp/x", "UPPER", "a_b", "a..b"):
        with pytest.raises(ValueError):
            store.manifest_path(unsafe)


def test_progress_order_ties_and_directory_paths(tmp_path: Path) -> None:
    _write(tmp_path, "older", "2025-01-01T00:00:00+00:00", 1)
    _write(tmp_path, "same-b", "2025-01-02T00:00:00+00:00", 2)
    _write(tmp_path, "same-a", "2025-01-02T00:00:00+00:00", 0)
    summaries = JobStore(tmp_path).list()
    assert [item.job_id for item in summaries] == ["same-a", "same-b", "older"]
    assert summaries[0].path == tmp_path / "same-a"
    assert summaries[1].completed_chunks == 2
    assert summaries[1].total_chunks == 3


def test_corrupt_manifest_isolated_and_generic(tmp_path: Path) -> None:
    directory = tmp_path / "broken"
    directory.mkdir()
    (directory / "manifest.json").write_text("not json; secret-token", encoding="utf-8")
    result = JobStore(tmp_path).list()
    assert len(result) == 1
    assert result[0].path == directory
    assert result[0].error == "manifest unavailable"
    assert "secret" not in result[0].error


def test_missing_root_and_symlink_job_ignored(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    assert JobStore(root).list() == ()
    target = tmp_path / "target"
    _write(root, "real", "2025-01-01T00:00:00+00:00")
    target.symlink_to(root / "real", target_is_directory=True)
    (root / "link").symlink_to(target, target_is_directory=True)
    assert [item.job_id for item in JobStore(root).list()] == ["real"]


def test_manifest_job_id_mismatch_is_corrupt(tmp_path: Path) -> None:
    directory = tmp_path / "outer"
    ManifestRepository.save(directory / "manifest.json", _manifest("inner", None))
    result = JobStore(tmp_path).list()
    assert result[0].error == "manifest unavailable"


def test_summary_is_frozen(tmp_path: Path) -> None:
    _write(tmp_path, "job", None)
    summary = JobStore(tmp_path).list()[0]
    with pytest.raises(AttributeError):
        summary.title = "changed"  # type: ignore[misc]


def test_delete_removes_only_named_job(tmp_path: Path) -> None:
    removed = _write(tmp_path, "remove-me", None)
    kept = _write(tmp_path, "keep-me", None)

    JobStore(tmp_path).delete("remove-me")

    assert not removed.exists()
    assert kept.is_dir()


def test_delete_rejects_missing_and_symlink_jobs(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    with pytest.raises(ValueError, match="does not exist"):
        store.delete("missing")
    target = _write(tmp_path, "target", None)
    (tmp_path / "linked").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="does not exist"):
        store.delete("linked")
    assert target.is_dir()
