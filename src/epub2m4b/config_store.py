from __future__ import annotations

import json
import os
import tempfile
import tomllib
from contextlib import suppress
from pathlib import Path
from typing import Any

from epub2m4b.exceptions import ConfigurationError

from .config import AppConfig

_SCHEMA_VERSION = 1
_FIELD_NAMES = frozenset(
    {
        "schema_version",
        "onboarding_complete",
        "provider",
        "model",
        "voice",
        "speed",
        "instructions",
        "cache_directory",
        "book_directory",
        "output_directory",
        "work_directory",
        "concurrency",
        "aac_bitrate_kbps",
        "maximum_estimated_cost_usd",
        "generation_options",
    }
)
_SECRET_TERMS = ("apikey", "authorization", "credential", "header", "password", "secret", "token")


def _is_secret_name(name: str) -> bool:
    folded = "".join(character for character in name.casefold() if character.isalnum())
    return any(term in folded for term in _SECRET_TERMS)


def _string(data: dict[str, Any], name: str, *, required: bool = True) -> str | None:
    value = data.get(name)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ConfigurationError(f"{name} must be a string")
    return value


def _number(data: dict[str, Any], name: str, expected: type[int] | type[float]) -> int | float:
    value = data.get(name)
    if expected is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigurationError(f"{name} must be a number")
        return float(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"{name} must be a {expected.__name__}")
    return value


def _boolean(data: dict[str, Any], name: str, *, default: bool) -> bool:
    value = data.get(name, default)
    if not isinstance(value, bool):
        raise ConfigurationError(f"{name} must be a boolean")
    return value


def _parse(raw: dict[str, Any]) -> AppConfig:
    unknown = set(raw) - _FIELD_NAMES
    if unknown:
        raise ConfigurationError(f"unknown configuration field: {sorted(unknown)[0]}")

    schema = raw.get("schema_version")
    if isinstance(schema, bool) or not isinstance(schema, int) or schema != _SCHEMA_VERSION:
        raise ConfigurationError("unsupported or missing schema_version")

    options = raw.get("generation_options", {})
    if not isinstance(options, dict):
        raise ConfigurationError("generation_options must be a table")
    for key, value in options.items():
        if not isinstance(key, str) or _is_secret_name(key) or not isinstance(value, str):
            raise ConfigurationError(
                "generation_options must contain non-secret string keys and values"
            )

    output = _string(raw, "output_directory", required=False)
    work = _string(raw, "work_directory", required=False)
    cache = _string(raw, "cache_directory", required=False)
    books = _string(raw, "book_directory", required=False)
    try:
        return AppConfig(
            onboarding_complete=_boolean(raw, "onboarding_complete", default=False),
            provider=_string(raw, "provider", required=False) or "openai",
            model=_string(raw, "model") or "",
            voice=_string(raw, "voice") or "",
            speed=_number(raw, "speed", float),
            instructions=_string(raw, "instructions") or "",
            cache_directory=Path(cache) if cache is not None else None,
            book_directory=Path(books) if books is not None else None,
            output_directory=Path(output) if output is not None else None,
            work_directory=Path(work) if work is not None else None,
            concurrency=_number(raw, "concurrency", int),
            aac_bitrate_kbps=_number(raw, "aac_bitrate_kbps", int),
            maximum_estimated_cost_usd=_number(raw, "maximum_estimated_cost_usd", float),
            generation_options=dict(options),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(str(exc)) from exc


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _serialize(config: AppConfig) -> str:
    lines = [
        "schema_version = 1",
        f"onboarding_complete = {'true' if config.onboarding_complete else 'false'}",
        f"provider = {_toml_string(config.provider)}",
        f"model = {_toml_string(config.model)}",
        f"voice = {_toml_string(config.voice)}",
        f"speed = {config.speed!r}",
        f"instructions = {_toml_string(config.instructions)}",
    ]
    if config.cache_directory is not None:
        lines.append(f"cache_directory = {_toml_string(str(config.cache_directory))}")
    if config.book_directory is not None:
        lines.append(f"book_directory = {_toml_string(str(config.book_directory))}")
    if config.output_directory is not None:
        lines.append(f"output_directory = {_toml_string(str(config.output_directory))}")
    if config.work_directory is not None:
        lines.append(f"work_directory = {_toml_string(str(config.work_directory))}")
    lines.extend(
        [
            f"concurrency = {config.concurrency}",
            f"aac_bitrate_kbps = {config.aac_bitrate_kbps}",
            f"maximum_estimated_cost_usd = {config.maximum_estimated_cost_usd!r}",
        ]
    )
    if config.generation_options:
        lines.append("")
        lines.append("[generation_options]")
        lines.extend(
            f"{_toml_string(key)} = {_toml_string(config.generation_options[key])}"
            for key in sorted(config.generation_options)
        )
    return "\n".join(lines) + "\n"


class ConfigRepository:
    """Load and atomically persist non-secret application configuration."""

    @staticmethod
    def load(path: Path) -> AppConfig:
        path = Path(path)
        if not path.exists():
            return AppConfig()
        try:
            with path.open("rb") as stream:
                raw = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigurationError(f"could not read configuration: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigurationError("configuration must be a TOML table")
        return _parse(raw)

    @staticmethod
    def save(path: Path, config: AppConfig) -> None:
        path = Path(path)
        if not isinstance(config, AppConfig):
            raise ConfigurationError("config must be an AppConfig")
        for key, value in config.generation_options.items():
            if not isinstance(key, str) or _is_secret_name(key) or not isinstance(value, str):
                raise ConfigurationError(
                    "generation_options must contain non-secret string keys and values"
                )
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        payload = _serialize(config).encode("utf-8")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=parent, delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
        except OSError as exc:
            raise ConfigurationError(f"could not save configuration: {exc}") from exc
        finally:
            if temporary is not None:
                with suppress(FileNotFoundError):
                    temporary.unlink()
