from __future__ import annotations

import os
from pathlib import Path

import pytest

from epub2m4b.config import AppConfig
from epub2m4b.config_store import ConfigRepository, ConfigurationError


def test_missing_file_returns_defaults(tmp_path: Path) -> None:
    assert ConfigRepository.load(tmp_path / "config.toml") == AppConfig()


def test_round_trip_all_fields(tmp_path: Path) -> None:
    config = AppConfig(
        onboarding_complete=True,
        model="model-☃",
        voice="marin",
        speed=0.875,
        instructions="Line one\nLine two — déjà vu",
        cache_directory=tmp_path / "cache folder",
        book_directory=tmp_path / "books",
        output_directory=tmp_path / "out folder",
        work_directory=tmp_path / "work",
        concurrency=4,
        aac_bitrate_kbps=128,
        maximum_estimated_cost_usd=3.5,
        generation_options={"zeta": "last", "alpha": "first"},
    )
    path = tmp_path / "nested" / "config.toml"
    ConfigRepository.save(path, config)
    assert ConfigRepository.load(path) == config
    assert path.read_bytes().decode("utf-8")


def test_save_is_deterministic(tmp_path: Path) -> None:
    config = AppConfig(generation_options={"z": "2", "a": "1"})
    first = tmp_path / "one.toml"
    second = tmp_path / "two.toml"
    ConfigRepository.save(first, config)
    ConfigRepository.save(second, config)
    assert first.read_bytes() == second.read_bytes()


def test_integer_values_for_float_settings_round_trip_as_floats(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    ConfigRepository.save(path, AppConfig(speed=1, maximum_estimated_cost_usd=0))

    loaded = ConfigRepository.load(path)

    assert loaded.speed == 1.0
    assert isinstance(loaded.speed, float)
    assert loaded.maximum_estimated_cost_usd == 0.0
    assert isinstance(loaded.maximum_estimated_cost_usd, float)


@pytest.mark.parametrize(
    "contents",
    [
        "schema_version = 1\nmodel = [",
        "schema_version = 2\n",
        "schema_version = 1\nunknown = true\n",
        'schema_version = 1\n[generation_options]\napi_key = "nope"\n',
        "schema_version = 1\nvoice = 4\n",
        "schema_version = 1\nconcurrency = true\n",
        "schema_version = 1\nonboarding_complete = 1\n",
    ],
)
def test_invalid_configuration_raises(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        ConfigRepository.load(path)


def test_failed_replace_preserves_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.toml"
    ConfigRepository.save(path, AppConfig(voice="old"))
    original = path.read_bytes()

    def fail_replace(source: os.PathLike[str] | str, destination: os.PathLike[str] | str) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("epub2m4b.config_store.os.replace", fail_replace)
    with pytest.raises(ConfigurationError):
        ConfigRepository.save(path, AppConfig(voice="new"))
    assert path.read_bytes() == original
    assert list(tmp_path.glob(".*.tmp")) == []


def test_save_revalidates_mutated_generation_options(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    ConfigRepository.save(path, AppConfig(voice="old"))
    original = path.read_bytes()
    config = AppConfig()
    config.generation_options["api-key"] = "secret"
    with pytest.raises(ConfigurationError):
        ConfigRepository.save(path, config)
    assert path.read_bytes() == original


def test_load_rejects_punctuation_variant_secret_option(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        'schema_version = 1\n[generation_options]\n"API KEY" = "secret"\n', encoding="utf-8"
    )
    with pytest.raises(ConfigurationError):
        ConfigRepository.load(path)


@pytest.mark.parametrize("field", ["cache_directory", "book_directory"])
def test_storage_paths_must_be_paths(field: str) -> None:
    values = {field: "not-a-path-object"}
    with pytest.raises(ValueError, match="directory must be a path"):
        AppConfig(**values)  # type: ignore[arg-type]


def test_configuration_error_is_epub2m4b_error(tmp_path: Path) -> None:
    from epub2m4b.exceptions import Epub2M4BError

    path = tmp_path / "config.toml"
    path.write_text("invalid toml =====", encoding="utf-8")
    with pytest.raises(Epub2M4BError):
        ConfigRepository.load(path)


def test_generation_options_rejects_header(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        'schema_version = 1\n[generation_options]\ncustom_header = "secret"\n', encoding="utf-8"
    )
    with pytest.raises(ConfigurationError):
        ConfigRepository.load(path)

