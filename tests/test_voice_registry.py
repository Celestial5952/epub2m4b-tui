import hashlib
import json
from pathlib import Path

import pytest

from epub2m4b.voice_registry import VoiceRegistry, VoiceRegistryError

ROOT = Path(__file__).parents[1] / "src" / "epub2m4b" / "resources" / "voice_samples"


def test_bundled_manifest_loads_all_verified_entries() -> None:
    registry = VoiceRegistry.load_bundled()
    assert len(registry.entries) == 13
    assert {entry.id for entry in registry.entries} == {
        "alloy",
        "ash",
        "ballad",
        "cedar",
        "coral",
        "echo",
        "fable",
        "marin",
        "nova",
        "onyx",
        "sage",
        "shimmer",
        "verse",
    }
    assert all(
        entry.path.is_file() and entry.path.read_bytes().startswith(b"OggS")
        for entry in registry.entries
    )


def test_bundled_manifest_loads_in_display_order() -> None:
    registry = VoiceRegistry.load(ROOT / "manifest.json")
    assert len(registry.entries) == 13
    assert registry.entries[0].id == "alloy"
    assert registry.get("marin").path.name == "marin.opus"


def test_manifest_rejects_bad_schema_and_duplicate_id(tmp_path: Path) -> None:
    asset = tmp_path / "voice.opus"
    asset.write_bytes(b"audio")
    base = {
        "id": "voice",
        "display_name": "Voice",
        "file": "voice.opus",
        "duration_seconds": 1.0,
        "size_bytes": 5,
        "sha256": hashlib.sha256(b"audio").hexdigest(),
    }
    for schema in (True, 2):
        (tmp_path / "manifest.json").write_text(
            json.dumps({"schema_version": schema, "voices": [base]}), encoding="utf-8"
        )
        with pytest.raises(VoiceRegistryError):
            VoiceRegistry.load(tmp_path / "manifest.json")
    duplicate = dict(base)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "voices": [base, duplicate]}), encoding="utf-8"
    )
    with pytest.raises(VoiceRegistryError):
        VoiceRegistry.load(tmp_path / "manifest.json")


@pytest.mark.parametrize(
    "relative", ["../voice.opus", "/tmp/voice.opus", "dir/voice.opus", "voice\\opus"]
)
def test_manifest_rejects_unsafe_paths(tmp_path: Path, relative: str) -> None:
    raw = {
        "schema_version": 1,
        "voices": [
            {
                "id": "voice",
                "display_name": "Voice",
                "file": relative,
                "duration_seconds": 1,
                "size_bytes": 1,
                "sha256": "0" * 64,
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(VoiceRegistryError):
        VoiceRegistry.load(path)


def test_manifest_rejects_integrity_mismatch_and_symlink(tmp_path: Path) -> None:
    asset = tmp_path / "voice.opus"
    asset.write_bytes(b"audio")
    raw = {
        "schema_version": 1,
        "voices": [
            {
                "id": "voice",
                "display_name": "Voice",
                "file": "voice.opus",
                "duration_seconds": 1,
                "size_bytes": 99,
                "sha256": "0" * 64,
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(VoiceRegistryError):
        VoiceRegistry.load(path)
    asset.unlink()
    asset.symlink_to(Path("/etc/hosts"))
    raw["voices"][0]["size_bytes"] = 1
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(VoiceRegistryError):
        VoiceRegistry.load(path)


def test_manifest_rejects_nonfinite_duration(tmp_path: Path) -> None:
    raw = {
        "schema_version": 1,
        "voices": [
            {
                "id": "voice",
                "display_name": "Voice",
                "file": "voice.opus",
                "duration_seconds": float("nan"),
                "size_bytes": 1,
                "sha256": "0" * 64,
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(VoiceRegistryError):
        VoiceRegistry.load(path)
