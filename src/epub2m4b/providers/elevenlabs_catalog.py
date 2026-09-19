"""Explicit ElevenLabs voice and model discovery (UNTESTED against the live API).

Catalog reads are never performed during startup or onboarding. The UI may call
this client only after the listener explicitly asks to browse provider assets.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from epub2m4b.exceptions import ProviderError

_MAX_CATALOG_BYTES = 8 * 1024 * 1024
_GetTransport = Callable[
    [str, Mapping[str, str], float], tuple[bytes, Mapping[str, str]]
]


class _HTTPStatusError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


@dataclass(frozen=True, slots=True)
class ElevenLabsVoice:
    id: str
    name: str
    category: str | None
    preview_url: str | None


@dataclass(frozen=True, slots=True)
class ElevenLabsVoicePage:
    voices: tuple[ElevenLabsVoice, ...]
    has_more: bool
    next_page_token: str | None


@dataclass(frozen=True, slots=True)
class ElevenLabsModel:
    id: str
    name: str
    maximum_text_length: int | None
    character_cost_multiplier: Decimal | None


class ElevenLabsCatalog:
    """Fetch immutable, validated ElevenLabs TTS catalog metadata on demand."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: _GetTransport | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("ElevenLabs API key must be nonblank")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout must be a finite positive number")
        self._api_key = api_key
        self._transport = transport or self._http_get
        self._timeout_seconds = timeout_seconds

    async def list_voices(
        self,
        *,
        search: str | None = None,
        page_size: int = 100,
        next_page_token: str | None = None,
    ) -> ElevenLabsVoicePage:
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= 100
        ):
            raise ValueError("page size must be between 1 and 100")
        for name, value in (("search", search), ("next page token", next_page_token)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a nonblank string")
        query: dict[str, str | int] = {
            "page_size": page_size,
            "sort": "name",
            "sort_direction": "asc",
            "include_total_count": "false",
        }
        if search is not None:
            query["search"] = search
        if next_page_token is not None:
            query["next_page_token"] = next_page_token
        payload = await self._get_json(
            f"https://api.elevenlabs.io/v2/voices?{urlencode(query)}"
        )
        try:
            if not isinstance(payload, dict):
                raise TypeError
            raw_voices = payload["voices"]
            has_more = payload["has_more"]
            token = payload.get("next_page_token")
            if not isinstance(raw_voices, list) or not isinstance(has_more, bool):
                raise TypeError
            if token is not None and not isinstance(token, str):
                raise TypeError
            voices = tuple(self._parse_voice(item) for item in raw_voices)
            if has_more and not token:
                raise TypeError
        except (KeyError, TypeError, ValueError):
            raise ProviderError(
                "ElevenLabs returned invalid voice catalog data", retryable=False
            ) from None
        return ElevenLabsVoicePage(voices, has_more, token or None)

    async def list_models(self) -> tuple[ElevenLabsModel, ...]:
        payload = await self._get_json("https://api.elevenlabs.io/v1/models")
        try:
            if not isinstance(payload, list):
                raise TypeError
            models = tuple(
                self._parse_model(item)
                for item in payload
                if isinstance(item, dict) and item.get("can_do_text_to_speech") is True
            )
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise ProviderError(
                "ElevenLabs returned invalid model catalog data", retryable=False
            ) from None
        return models

    async def _get_json(self, url: str) -> object:
        headers = {"Accept": "application/json", "xi-api-key": self._api_key}
        try:
            body, _ = await asyncio.to_thread(
                self._transport, url, headers, self._timeout_seconds
            )
        except Exception as exc:
            raise self._provider_error(exc) from None
        if not isinstance(body, bytes) or not body or len(body) > _MAX_CATALOG_BYTES:
            raise ProviderError("ElevenLabs returned invalid catalog data", retryable=False)
        try:
            return json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderError(
                "ElevenLabs returned invalid catalog data", retryable=False
            ) from None

    @staticmethod
    def _parse_voice(value: object) -> ElevenLabsVoice:
        if not isinstance(value, dict):
            raise TypeError
        voice_id = value["voice_id"]
        name = value["name"]
        category = value.get("category")
        preview = value.get("preview_url")
        if not isinstance(voice_id, str) or not voice_id.strip():
            raise TypeError
        if not isinstance(name, str) or not name.strip():
            raise TypeError
        if category is not None and not isinstance(category, str):
            raise TypeError
        if preview is not None and not isinstance(preview, str):
            raise TypeError
        return ElevenLabsVoice(voice_id, name, category or None, preview or None)

    @staticmethod
    def _parse_model(value: object) -> ElevenLabsModel:
        if not isinstance(value, dict):
            raise TypeError
        model_id = value["model_id"]
        name = value.get("name") or model_id
        maximum = value.get("maximum_text_length_per_request")
        rates = value.get("model_rates")
        if not isinstance(model_id, str) or not model_id.strip():
            raise TypeError
        if not isinstance(name, str) or not name.strip():
            raise TypeError
        if maximum is not None and (
            isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0
        ):
            raise TypeError
        multiplier: Decimal | None = None
        if rates is not None:
            if not isinstance(rates, dict):
                raise TypeError
            raw_multiplier = rates.get("character_cost_multiplier")
            if raw_multiplier is not None:
                multiplier = Decimal(str(raw_multiplier))
                if not multiplier.is_finite() or multiplier <= 0:
                    raise ValueError
        return ElevenLabsModel(model_id, name, maximum, multiplier)

    @staticmethod
    def _http_get(
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> tuple[bytes, Mapping[str, str]]:
        request = Request(url, headers=dict(headers), method="GET")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
                status = getattr(response, "status", 200)
                if not isinstance(status, int) or not 200 <= status < 300:
                    raise _HTTPStatusError(status if isinstance(status, int) else 500)
                body = response.read(_MAX_CATALOG_BYTES + 1)
                response_headers = dict(response.headers.items())
        except HTTPError as exc:
            raise _HTTPStatusError(exc.code) from None
        except URLError as exc:
            raise ConnectionError from exc
        return body, response_headers

    @staticmethod
    def _provider_error(exc: BaseException) -> ProviderError:
        status = getattr(exc, "status", None)
        if isinstance(status, int):
            retryable = status in {408, 409, 429} or status >= 500
            if status in {401, 403}:
                message = "ElevenLabs authentication or permission failed"
            elif status == 429:
                message = "ElevenLabs rate limit or quota was reached"
            elif 400 <= status < 500:
                message = "ElevenLabs catalog request was rejected"
            else:
                message = "ElevenLabs catalog service failed"
            return ProviderError(message, retryable=retryable)
        retryable = isinstance(exc, (TimeoutError, ConnectionError, asyncio.TimeoutError))
        return ProviderError(
            "ElevenLabs network request failed" if retryable else "ElevenLabs request failed",
            retryable=retryable,
        )


__all__ = [
    "ElevenLabsCatalog",
    "ElevenLabsModel",
    "ElevenLabsVoice",
    "ElevenLabsVoicePage",
]
