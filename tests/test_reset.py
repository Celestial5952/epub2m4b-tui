from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from epub2m4b.app.audit import AuditLog
from epub2m4b.app.reset import force_reonboard
from epub2m4b.config import AppConfig
from epub2m4b.config_store import ConfigRepository


class Credentials:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete(self, provider_id: str) -> None:
        self.deleted.append(provider_id)


def test_force_reonboard_exports_nonsecret_history_and_clears_owned_state(tmp_path: Path) -> None:
    config_path = tmp_path / "config" / "config.toml"
    ConfigRepository.save(
        config_path,
        AppConfig(voice="nova", book_directory=tmp_path / "books", output_directory=tmp_path / "output"),
    )
    audit = AuditLog(tmp_path / "state" / "logs" / "audit.jsonl")
    audit.record("failure", "Authorization: Bearer sk-test-secret-value")
    jobs_root = tmp_path / "state" / "jobs"
    cache_root = tmp_path / "cache" / "audio"
    (jobs_root / "job-1").mkdir(parents=True)
    (jobs_root / "job-1" / "manifest.json").write_text("{}", encoding="utf-8")
    cache_root.mkdir(parents=True)
    (cache_root / "chunk.wav").write_bytes(b"audio")
    output = tmp_path / "output" / "book.m4b"
    output.parent.mkdir()
    output.write_bytes(b"finished")
    credentials = Credentials()
    export = tmp_path / "epub2m4b-reset.json"

    result = force_reonboard(
        config_path=config_path,
        audit=audit,
        jobs_root=jobs_root,
        cache_root=cache_root,
        credentials=credentials,  # type: ignore[arg-type]
        export_path=export,
        exported_at=datetime(2026, 9, 17, tzinfo=UTC),
    )

    assert result == export
    saved = json.loads(export.read_text(encoding="utf-8"))
    assert saved["settings"]["voice"] == "nova"
    assert saved["credentials_exported"] is False
    assert "sk-test-secret-value" not in export.read_text(encoding="utf-8")
    assert credentials.deleted == ["openai", "elevenlabs"]
    assert not config_path.exists()
    assert not audit.path.exists()
    assert not jobs_root.exists()
    assert not cache_root.exists()
    assert output.read_bytes() == b"finished"
