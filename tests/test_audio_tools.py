from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from epub2m4b.audio.tools import probe_duration, write_concat_list
from epub2m4b.exceptions import AudioValidationError, ExternalToolError


def _audio(path: Path, content: bytes = b"audio") -> Path:
    path.write_bytes(content)
    return path


def test_probe_duration_uses_safe_machine_readable_command(tmp_path: Path) -> None:
    source = _audio(tmp_path / "book chapter.wav")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="12.5\n", stderr="secret")

    assert probe_duration(source, runner=runner, resolver=lambda _: "/usr/bin/ffprobe") == 12.5
    command, kwargs = calls[0]
    assert command == [
        "/usr/bin/ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(source),
    ]
    assert kwargs["shell"] is False


@pytest.mark.parametrize("output", ["", "nan", "inf", "-1", "0", "one\ntwo"])
def test_probe_duration_rejects_invalid_output(tmp_path: Path, output: str) -> None:
    source = _audio(tmp_path / "input.wav")

    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, stdout=output, stderr="private")

    with pytest.raises(AudioValidationError):
        probe_duration(source, runner=runner, resolver=lambda _: "ffprobe")


def test_probe_duration_reports_missing_tool_and_failed_process(tmp_path: Path) -> None:
    source = _audio(tmp_path / "input.wav")
    with pytest.raises(ExternalToolError, match="not found"):
        probe_duration(source, resolver=lambda _: None)

    def failed(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 2, stdout="", stderr="do not leak")

    with pytest.raises(ExternalToolError, match="ffprobe failed"):
        probe_duration(source, runner=failed, resolver=lambda _: "ffprobe")


def test_probe_duration_rejects_missing_empty_and_symlink_inputs(tmp_path: Path) -> None:
    with pytest.raises(AudioValidationError):
        probe_duration(tmp_path / "missing.wav", resolver=lambda _: "ffprobe")
    empty = tmp_path / "empty.wav"
    empty.touch()
    with pytest.raises(AudioValidationError):
        probe_duration(empty, resolver=lambda _: "ffprobe")
    source = _audio(tmp_path / "source.wav")
    link = tmp_path / "link.wav"
    link.symlink_to(source)
    with pytest.raises(AudioValidationError):
        probe_duration(link, resolver=lambda _: "ffprobe")


def test_write_concat_list_is_deterministic_and_escapes_paths(tmp_path: Path) -> None:
    first = _audio(tmp_path / "a one.wav")
    second = _audio(tmp_path / "c\\d's.wav")
    destination = tmp_path / "lists" / "concat.txt"
    destination.parent.mkdir()
    write_concat_list([first, second], destination)
    expected = f"file '{first}'\nfile '{str(second).replace(chr(92), chr(92) * 2).replace(chr(39), chr(92) + chr(39))}'\n"
    assert destination.read_bytes() == expected.encode()
    before = destination.read_bytes()
    write_concat_list([first, second], destination)
    assert destination.read_bytes() == before


def test_write_concat_list_rejects_invalid_inputs_and_newlines(tmp_path: Path) -> None:
    destination = tmp_path / "concat.txt"
    with pytest.raises(AudioValidationError):
        write_concat_list([], destination)
    empty = tmp_path / "empty.wav"
    empty.touch()
    with pytest.raises(AudioValidationError):
        write_concat_list([empty], destination)
    source = _audio(tmp_path / "source.wav")
    link = tmp_path / "link.wav"
    link.symlink_to(source)
    with pytest.raises(AudioValidationError):
        write_concat_list([link], destination)
    newline = _audio(tmp_path / "line\nfeed.wav")
    with pytest.raises(AudioValidationError):
        write_concat_list([newline], destination)


def test_write_concat_list_failed_replace_preserves_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _audio(tmp_path / "input.wav")
    destination = tmp_path / "concat.txt"
    destination.write_text("previous\n", encoding="utf-8")

    def fail_replace(source_path: str | Path, target_path: str | Path) -> None:
        raise OSError("private failure")

    monkeypatch.setattr("epub2m4b.audio.tools.os.replace", fail_replace)
    with pytest.raises(ExternalToolError):
        write_concat_list([source], destination)
    assert destination.read_text(encoding="utf-8") == "previous\n"
    assert not list(tmp_path.glob(".concat.txt.*.tmp"))
