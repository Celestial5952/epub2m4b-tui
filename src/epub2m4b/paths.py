"""Application paths following the XDG base-directory specification."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_APP_DIRECTORY = "epub2m4b"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """The application-owned XDG directories.

    ``resolve`` only computes paths.  Call :meth:`ensure` when the directories
    need to be created on disk.
    """

    config: Path
    data: Path
    cache: Path
    state: Path

    @classmethod
    def resolve(
        cls,
        env: Mapping[str, str] | None = None,
        home: str | Path | None = None,
    ) -> AppPaths:
        """Resolve application paths from XDG variables and a home directory.

        Empty XDG values are treated the same as missing values.  A supplied
        ``home`` takes precedence over ``HOME`` in ``env`` and makes expansion
        of ``~`` deterministic for callers and tests.
        """

        variables = os.environ if env is None else env
        home_path = Path(home) if home is not None else Path(variables.get("HOME", Path.home()))

        defaults = {
            "XDG_CONFIG_HOME": home_path / ".config",
            "XDG_DATA_HOME": home_path / ".local" / "share",
            "XDG_CACHE_HOME": home_path / ".cache",
            "XDG_STATE_HOME": home_path / ".local" / "state",
        }

        def base_directory(name: str) -> Path:
            value = variables.get(name, "")
            base = _expand_user(value, home_path) if value else defaults[name]
            return base / _APP_DIRECTORY

        return cls(
            config=base_directory("XDG_CONFIG_HOME"),
            data=base_directory("XDG_DATA_HOME"),
            cache=base_directory("XDG_CACHE_HOME"),
            state=base_directory("XDG_STATE_HOME"),
        )

    def ensure(self) -> AppPaths:
        """Create all application-owned directories and return this object."""

        for directory in (self.config, self.data, self.cache, self.state):
            directory.mkdir(parents=True, exist_ok=True)
        return self


def _expand_user(value: str, home: Path) -> Path:
    """Expand only the current user's ``~`` using the supplied home path."""

    if value == "~":
        return home
    if value.startswith("~/"):
        return home / value[2:]
    return Path(value)
