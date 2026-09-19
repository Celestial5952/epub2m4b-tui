"""Small, shell-free ffplay controller for voice auditions."""

from __future__ import annotations

import math
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from epub2m4b.exceptions import AudioValidationError, ExternalToolError


class AudioPlayer:
    def __init__(
        self,
        *,
        resolver: Callable[[str], str | None] = shutil.which,
        process_factory: Callable[..., Any] = subprocess.Popen,
        wait_timeout: float = 1.0,
    ) -> None:
        self._resolver = resolver
        self._process_factory = process_factory
        if (
            not isinstance(wait_timeout, (int, float))
            or isinstance(wait_timeout, bool)
            or not math.isfinite(wait_timeout)
            or wait_timeout <= 0
        ):
            raise ValueError("wait_timeout must be finite and greater than zero")
        self._wait_timeout = wait_timeout
        self._process: Any | None = None

    @property
    def playing(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def play(self, path: Path) -> None:
        candidate = Path(path)
        if candidate.is_symlink() or not candidate.is_file():
            raise AudioValidationError("audio input is missing or symlinked")
        try:
            if candidate.stat().st_size <= 0:
                raise AudioValidationError("audio input is empty")
        except OSError as exc:
            raise AudioValidationError("audio input is unavailable") from exc
        self.stop()
        executable = self._resolver("ffplay")
        if not executable:
            raise ExternalToolError("ffplay is not available on PATH")
        argv = [executable, "-nodisp", "-autoexit", "-loglevel", "error", str(candidate)]
        try:
            self._process = self._process_factory(
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self._process = None
            raise ExternalToolError("could not start ffplay") from exc

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            if process.poll() is not None:
                process.wait()
                return
            process.terminate()
            try:
                process.wait(timeout=self._wait_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        except (OSError, subprocess.SubprocessError):
            # Stopping is best-effort, but always forgets the child so it is idempotent.
            return

    def shutdown(self) -> None:
        self.stop()
