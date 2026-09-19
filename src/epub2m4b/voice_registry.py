"""Validated, immutable access to the bundled voice audition files."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from epub2m4b.exceptions import Epub2M4BError


class VoiceRegistryError(Epub2M4BError):
    """The bundled voice manifest or one of its assets is invalid."""


@dataclass(frozen=True, slots=True)
class VoiceEntry:
    """One verified bundled voice audition asset."""

    id: str
    display_name: str
    path: Path
    duration_seconds: float
    size_bytes: int
    sha256: str


class VoiceRegistry:
    """Load and verify the bundled voice manifest without provider access."""

    def __init__(self, manifest_path: Path, entries: tuple[VoiceEntry, ...]) -> None:
        self.manifest_path = Path(manifest_path)
        self.entries = entries
        self._by_id = MappingProxyType({entry.id: entry for entry in entries})

    @classmethod
    def load_bundled(cls) -> VoiceRegistry:
        """Load the voice samples installed inside the application package."""

        return cls.load(Path(__file__).parent / "resources" / "voice_samples" / "manifest.json")

    @classmethod
    def load(cls, manifest_path: Path) -> VoiceRegistry:
        manifest = Path(manifest_path)
        try:
            with manifest.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VoiceRegistryError("could not read voice manifest") from exc
        if (
            not isinstance(raw, dict)
            or isinstance(raw.get("schema_version"), bool)
            or raw.get("schema_version") != 1
        ):
            raise VoiceRegistryError("unsupported voice manifest schema")
        voices = raw.get("voices")
        if not isinstance(voices, list):
            raise VoiceRegistryError("voice manifest voices must be a list")
        base = manifest.parent.resolve()
        entries: list[VoiceEntry] = []
        seen: set[str] = set()
        for item in voices:
            if not isinstance(item, dict):
                raise VoiceRegistryError("voice entry must be an object")
            try:
                voice_id = item["id"]
                display_name = item["display_name"]
                relative = item["file"]
                duration = item["duration_seconds"]
                size = item["size_bytes"]
                expected_hash = item["sha256"]
            except KeyError as exc:
                raise VoiceRegistryError("voice entry is missing a required field") from exc
            if (
                not isinstance(voice_id, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", voice_id) is None
                or voice_id in seen
            ):
                raise VoiceRegistryError("voice entry has an invalid or duplicate id")
            if not isinstance(display_name, str) or not display_name.strip():
                raise VoiceRegistryError("voice display_name must be non-empty")
            if (
                not isinstance(relative, str)
                or not relative
                or "\\" in relative
                or "\x00" in relative
            ):
                raise VoiceRegistryError("voice file path is unsafe")
            file_path = Path(relative)
            if file_path.is_absolute() or ".." in file_path.parts or len(file_path.parts) != 1:
                raise VoiceRegistryError("voice file path must be a single safe relative name")
            if (
                isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or duration <= 0
                or not math.isfinite(duration)
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size <= 0
                or not isinstance(expected_hash, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
            ):
                raise VoiceRegistryError("voice entry has invalid integrity metadata")
            candidate = manifest.parent / file_path
            resolved = candidate.resolve(strict=False)
            if resolved.parent != base or candidate.is_symlink() or not candidate.is_file():
                raise VoiceRegistryError("voice asset is missing, unsafe, or not a regular file")
            try:
                actual_size = candidate.stat().st_size
                actual_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
            except OSError as exc:
                raise VoiceRegistryError("could not verify voice asset") from exc
            if actual_size != size or actual_hash != expected_hash:
                raise VoiceRegistryError("voice asset integrity does not match manifest")
            entries.append(
                VoiceEntry(
                    voice_id,
                    display_name,
                    candidate,
                    float(duration),
                    size,
                    expected_hash,
                )
            )
            seen.add(voice_id)
        return cls(manifest, tuple(entries))

    def get(self, voice_id: str) -> VoiceEntry:
        try:
            return self._by_id[voice_id]
        except KeyError as exc:
            raise KeyError(voice_id) from exc
