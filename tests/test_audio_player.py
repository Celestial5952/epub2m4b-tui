import subprocess
from pathlib import Path

import pytest

from epub2m4b.audio.player import AudioPlayer
from epub2m4b.exceptions import AudioValidationError, ExternalToolError


class FakeProcess:
    def __init__(self, *, running=True, timeout=False):
        self.returncode = None if running else 0
        self.timeout = timeout
        self.terminated = self.killed = False
        self.waits = []

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        if not self.timeout:
            self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if timeout is not None and self.timeout and not self.killed:
            raise subprocess.TimeoutExpired("ffplay", timeout)
        return self.returncode


def test_play_uses_safe_argv_and_stop_lifecycle(tmp_path: Path) -> None:
    audio = tmp_path / "sample.opus"
    audio.write_bytes(b"audio")
    calls = []
    proc = FakeProcess()

    def factory(*args, **kwargs):
        calls.append((args, kwargs))
        return proc

    player = AudioPlayer(resolver=lambda name: "/usr/bin/ffplay", process_factory=factory)
    player.play(audio)
    assert calls[0][0][0] == [
        "/usr/bin/ffplay",
        "-nodisp",
        "-autoexit",
        "-loglevel",
        "error",
        str(audio),
    ]
    assert calls[0][1]["shell"] is False
    assert player.playing
    player.stop()
    assert proc.terminated
    player.stop()


def test_play_stops_old_process_before_missing_tool(tmp_path: Path) -> None:
    old = FakeProcess()
    player = AudioPlayer(resolver=lambda name: None, process_factory=lambda *a, **k: old)
    player._process = old
    audio = tmp_path / "sample"
    audio.write_bytes(b"audio")
    with pytest.raises(ExternalToolError):
        player.play(audio)
    assert old.terminated


def test_stop_escalates_to_kill_and_shutdown_is_idempotent() -> None:
    proc = FakeProcess(timeout=True)
    player = AudioPlayer(process_factory=lambda *a, **k: proc)
    player._process = proc
    player.stop()
    player.shutdown()
    assert proc.terminated and proc.killed


def test_missing_or_empty_input_and_ffplay_are_typed(tmp_path: Path) -> None:
    with pytest.raises(AudioValidationError):
        AudioPlayer().play(tmp_path / "missing")
    empty = tmp_path / "empty"
    empty.touch()
    with pytest.raises(AudioValidationError):
        AudioPlayer().play(empty)
    data = tmp_path / "data"
    data.write_bytes(b"x")
    with pytest.raises(ExternalToolError):
        AudioPlayer(resolver=lambda name: None).play(data)


def test_wait_timeout_validation() -> None:
    with pytest.raises(ValueError):
        AudioPlayer(wait_timeout=0)
    with pytest.raises(ValueError):
        AudioPlayer(wait_timeout=float("inf"))
