"""Small, safe wrappers for FFprobe and FFmpeg concat-list inputs."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from contextlib import suppress
from pathlib import Path

from epub2m4b.exceptions import AudioValidationError, ExternalToolError

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
ToolResolver = Callable[[str], str | None]


def _validate_input(path: Path) -> None:
    """Require a real, non-empty regular file without following symlinks."""
    if path.is_symlink() or not path.is_file():
        raise AudioValidationError("Audio input must be a regular, non-symlinked file")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise AudioValidationError("Audio input could not be inspected") from exc
    if size <= 0:
        raise AudioValidationError("Audio input must be non-empty")


def probe_duration(
    path: str | os.PathLike[str],
    *,
    runner: CommandRunner | None = None,
    resolver: ToolResolver | None = None,
) -> float:
    """Return a positive finite duration reported by ``ffprobe``.

    The optional hooks exist so callers and tests can supply deterministic process
    and PATH behavior.  Process output is intentionally never included in errors.
    """
    audio_path = Path(path)
    _validate_input(audio_path)
    find_tool = resolver or shutil.which
    executable = find_tool("ffprobe")
    if not executable:
        raise ExternalToolError("ffprobe was not found on PATH")

    command = [
        executable,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    invoke = runner or subprocess.run
    try:
        result = invoke(
            command,
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ExternalToolError("ffprobe could not be executed") from exc
    if result.returncode != 0:
        raise ExternalToolError("ffprobe failed to inspect the audio file")
    output = result.stdout.strip() if isinstance(result.stdout, str) else ""
    try:
        duration = float(output)
    except (TypeError, ValueError) as exc:
        raise AudioValidationError("ffprobe returned an invalid duration") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise AudioValidationError("ffprobe returned an invalid duration")
    return duration


def _escape_concat_path(path: Path) -> str:
    text = str(path)
    if "\n" in text or "\r" in text:
        raise AudioValidationError("Audio paths containing newlines are unsupported")
    return text.replace("\\", "\\\\").replace("'", "\\'")


def write_concat_list(
    paths: Sequence[str | os.PathLike[str]],
    destination: str | os.PathLike[str],
) -> None:
    """Atomically write an FFmpeg concat-demuxer list in the supplied order."""
    if not paths:
        raise AudioValidationError("At least one audio input is required")
    inputs = tuple(Path(path) for path in paths)
    for path in inputs:
        _validate_input(path)
    lines = [f"file '{_escape_concat_path(path)}'\n" for path in inputs]
    payload = "".join(lines).encode("utf-8")
    target = Path(destination)
    parent = target.parent if str(target.parent) else Path(".")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{target.name}.", suffix=".tmp", dir=parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    except OSError as exc:
        raise ExternalToolError("Could not write the concat list") from exc
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink()
