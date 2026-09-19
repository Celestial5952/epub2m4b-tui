from pathlib import Path

from epub2m4b.paths import AppPaths


def test_resolve_honors_all_xdg_overrides(tmp_path: Path) -> None:
    env = {
        "HOME": str(tmp_path / "ignored-home"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }

    paths = AppPaths.resolve(env=env)

    assert paths == AppPaths(
        config=tmp_path / "config" / "epub2m4b",
        data=tmp_path / "data" / "epub2m4b",
        cache=tmp_path / "cache" / "epub2m4b",
        state=tmp_path / "state" / "epub2m4b",
    )


def test_resolve_supports_partial_overrides_and_supplied_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    paths = AppPaths.resolve(
        env={"XDG_DATA_HOME": str(tmp_path / "data")},
        home=home,
    )

    assert paths.config == home / ".config" / "epub2m4b"
    assert paths.data == tmp_path / "data" / "epub2m4b"
    assert paths.cache == home / ".cache" / "epub2m4b"
    assert paths.state == home / ".local" / "state" / "epub2m4b"


def test_empty_xdg_values_use_home_fallbacks(tmp_path: Path) -> None:
    home = tmp_path / "home"
    paths = AppPaths.resolve(
        env={
            "XDG_CONFIG_HOME": "",
            "XDG_DATA_HOME": "",
            "XDG_CACHE_HOME": "",
            "XDG_STATE_HOME": "",
        },
        home=home,
    )

    assert paths.config == home / ".config" / "epub2m4b"
    assert paths.data == home / ".local" / "share" / "epub2m4b"
    assert paths.cache == home / ".cache" / "epub2m4b"
    assert paths.state == home / ".local" / "state" / "epub2m4b"


def test_tilde_override_uses_supplied_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    paths = AppPaths.resolve(env={"XDG_CACHE_HOME": "~/custom-cache"}, home=home)

    assert paths.cache == home / "custom-cache" / "epub2m4b"


def test_resolve_has_no_side_effects(tmp_path: Path) -> None:
    paths = AppPaths.resolve(home=tmp_path / "home")

    assert not (tmp_path / "home").exists()
    assert all(
        not directory.exists() for directory in (paths.config, paths.data, paths.cache, paths.state)
    )


def test_ensure_creates_directories_and_returns_same_object(tmp_path: Path) -> None:
    paths = AppPaths.resolve(home=tmp_path / "home")

    ensured = paths.ensure()

    assert ensured is paths
    assert all(
        directory.is_dir() for directory in (paths.config, paths.data, paths.cache, paths.state)
    )
