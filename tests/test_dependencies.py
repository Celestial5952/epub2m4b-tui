from pathlib import Path

import pytest

from epub2m4b.dependencies import DependencyReport, DependencyStatus, check_dependencies


def test_all_tools_are_resolved_in_stable_order() -> None:
    calls: list[str] = []

    def resolver(name: str) -> str:
        calls.append(name)
        return f"/usr/bin/{name}"

    report = check_dependencies(resolver)
    assert calls == ["ffmpeg", "ffprobe", "ffplay"]
    assert report.entries == (
        DependencyStatus("ffmpeg", True, True, Path("/usr/bin/ffmpeg")),
        DependencyStatus("ffprobe", True, True, Path("/usr/bin/ffprobe")),
        DependencyStatus("ffplay", False, True, Path("/usr/bin/ffplay")),
    )
    assert report.required_available
    assert report.preview_available


def test_required_and_optional_missing_are_summarized_separately() -> None:
    report = check_dependencies(lambda name: "/bin/tool" if name == "ffmpeg" else None)
    assert report.entries[0].available
    assert not report.entries[1].available
    assert not report.entries[2].available
    assert not report.required_available
    assert not report.preview_available


def test_bad_paths_and_resolver_exceptions_are_isolated() -> None:
    def resolver(name: str) -> object:
        if name == "ffmpeg":
            return "   "
        if name == "ffprobe":
            raise RuntimeError("secret resolver details")
        return 42

    report = check_dependencies(resolver)
    assert all(not entry.available and entry.path is None for entry in report.entries)


def test_report_and_status_are_immutable() -> None:
    status = DependencyStatus("ffmpeg", True, True, Path("/bin/ffmpeg"))
    report = DependencyReport((status,))
    with pytest.raises(AttributeError):
        status.available = False  # type: ignore[misc]
    with pytest.raises(AttributeError):
        report.entries = ()  # type: ignore[misc]
