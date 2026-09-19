from __future__ import annotations

import hashlib
import json
from pathlib import Path

SAMPLE_ROOT = Path(__file__).parents[1] / "src" / "epub2m4b" / "resources" / "voice_samples"
EXPECTED_VOICES = {
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


def test_voice_sample_manifest_and_assets_are_complete() -> None:
    manifest = json.loads((SAMPLE_ROOT / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 1
    assert manifest["model"] == "gpt-4o-mini-tts"
    assert manifest["format"] == "opus"
    assert manifest["sentence"].strip()
    assert {entry["id"] for entry in manifest["voices"]} == EXPECTED_VOICES
    assert len(manifest["voices"]) == len(EXPECTED_VOICES)

    hashes: set[str] = set()
    total_size = 0
    for entry in manifest["voices"]:
        relative = Path(entry["file"])
        assert relative.name == entry["file"]
        sample = SAMPLE_ROOT / relative
        content = sample.read_bytes()
        digest = hashlib.sha256(content).hexdigest()

        assert content.startswith(b"OggS")
        assert len(content) == entry["size_bytes"]
        assert digest == entry["sha256"]
        assert digest not in hashes
        assert entry["duration_seconds"] > 0
        hashes.add(digest)
        total_size += len(content)

    assert total_size < 2_000_000
