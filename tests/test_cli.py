from __future__ import annotations

import pytest

from epub2m4b import cli


class _ServiceFactory:
    created = object()

    @classmethod
    def create_default(cls) -> object:
        return cls.created


class _App:
    instances: list[_App] = []

    def __init__(self, service: object) -> None:
        self.service = service
        self.ran = False
        self.instances.append(self)

    def run(self) -> None:
        self.ran = True


def test_main_bootstraps_and_runs_textual_app(monkeypatch: pytest.MonkeyPatch) -> None:
    _App.instances.clear()
    monkeypatch.setattr(cli, "LocalApplicationService", _ServiceFactory)
    monkeypatch.setattr(cli, "EPUB2M4BApp", _App)

    assert cli.main([]) == 0
    assert len(_App.instances) == 1
    assert _App.instances[0].service is _ServiceFactory.created
    assert _App.instances[0].ran


def test_help_and_version_exit_before_bootstrap(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Forbidden:
        @classmethod
        def create_default(cls) -> object:
            raise AssertionError("bootstrap must not run")

    monkeypatch.setattr(cli, "LocalApplicationService", Forbidden)
    for option, expected in (("--help", "Convert EPUB"), ("--version", "0.1.0")):
        with pytest.raises(SystemExit) as caught:
            cli.main([option])
        assert caught.value.code == 0
        assert expected in capsys.readouterr().out
