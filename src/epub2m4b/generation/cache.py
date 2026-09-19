"""Deterministic, validation-aware storage for generated narration audio."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from epub2m4b.models import Chunk

_GENERATION_HASH = re.compile(r"^[0-9a-f]{64}$")


class AudioCache:
    """Map chunk generation identities to durable audio paths.

    Constructing a cache is deliberately side-effect free.  Callers should
    invoke :meth:`ensure` at the point where they are ready to create the
    cache's directories.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @property
    def narration_root(self) -> Path:
        return self.root / "narration"

    @property
    def preview_root(self) -> Path:
        return self.root / "previews"

    def ensure(self) -> AudioCache:
        """Create cache namespaces and return this cache."""

        self.narration_root.mkdir(parents=True, exist_ok=True)
        self.preview_root.mkdir(parents=True, exist_ok=True)
        return self

    def path_for(self, chunk: Chunk) -> Path:
        """Return the deterministic WAV path for ``chunk`` without I/O."""

        generation_hash = _validated_generation_hash(chunk.generation_hash)
        return self.narration_root / generation_hash[:2] / f"{generation_hash}.wav"

    def lookup(
        self,
        chunk: Chunk,
        validator: Callable[[Path], bool],
    ) -> Path | None:
        """Return a valid cached file, treating all validation failures as misses."""

        path = self.path_for(chunk)
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
                return None
            if not validator(path):
                return None
        except Exception:
            return None
        return path


def _validated_generation_hash(value: str) -> str:
    if not isinstance(value, str) or _GENERATION_HASH.fullmatch(value) is None:
        raise ValueError("generation hash must be exactly 64 lowercase hexadecimal characters")
    return value
