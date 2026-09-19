"""ElevenLabs text-to-speech provider (UNTESTED against the live API).

The adapter uses the documented HTTP endpoint directly so importing it never
loads a third-party SDK or performs network access. ElevenLabs returns raw
signed 16-bit PCM for ``pcm_24000``; the adapter wraps that stream in a WAV
container before it reaches the durable audio cache.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
import uuid
import wave
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from epub2m4b.exceptions import ProviderError
from epub2m4b.providers.base import SynthesisRequest, SynthesisResult

_SAMPLE_RATE = 24_000
_SAMPLE_WIDTH = 2
_CHANNELS = 1
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_Transport = Callable[
    [str, bytes, Mapping[str, str], float], tuple[bytes, Mapping[str, str]]
]


class _HTTPStatusError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


class ElevenLabsTTSProvider:
    """Convert an ElevenLabs PCM response into a validated, atomic WAV."""

    name = "elevenlabs"
    _RESERVED_OPTIONS = frozenset({"text", "model_id", "voice_id", "output_format"})

    def __init__(
        self,
        api_key: str,
        *,
        transport: _Transport | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("ElevenLabs API key must be nonblank")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout must be a finite positive number")
        self._api_key = api_key
        self._transport = transport or self._http_post
        self._timeout_seconds = timeout_seconds

    async def synthesize(self, request: SynthesisRequest, destination: Path) -> SynthesisResult:
        """Synthesize one WAV without blocking the event loop."""

        return await asyncio.to_thread(self._synthesize_sync, request, Path(destination))

    def _synthesize_sync(self, request: SynthesisRequest, destination: Path) -> SynthesisResult:
        collisions = sorted(self._RESERVED_OPTIONS.intersection(request.options))
        if collisions:
            raise ProviderError(
                "request options conflict with required speech fields", retryable=False
            )
        if os.path.lexists(destination):
            raise ProviderError("destination already exists", retryable=False)

        options = dict(request.options)
        voice_settings = options.pop("voice_settings", {})
        if not isinstance(voice_settings, dict) or any(
            not isinstance(key, str) for key in voice_settings
        ):
            raise ProviderError("voice settings must be a string-keyed object", retryable=False)
        if "speed" in voice_settings and voice_settings["speed"] != request.speed:
            raise ProviderError("voice speed conflicts with request speed", retryable=False)
        voice_settings = {**voice_settings, "speed": request.speed}
        payload: dict[str, Any] = {
            "text": request.text,
            "model_id": request.model,
            "voice_settings": voice_settings,
            **options,
        }
        try:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError):
            raise ProviderError(
                "request options are not JSON serializable", retryable=False
            ) from None

        voice_id = quote(request.voice, safe="")
        query = urlencode({"output_format": "pcm_24000"})
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?{query}"
        headers = {
            "Accept": "audio/pcm",
            "Content-Type": "application/json",
            "xi-api-key": self._api_key,
        }
        try:
            pcm, response_headers = self._transport(
                url, body, headers, self._timeout_seconds
            )
        except Exception as exc:
            raise self._provider_error(exc) from None

        temporary: Path | None = None
        try:
            self._validate_pcm(pcm)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
            with temporary.open("xb") as raw, wave.open(raw, "wb") as audio:
                audio.setnchannels(_CHANNELS)
                audio.setsampwidth(_SAMPLE_WIDTH)
                audio.setframerate(_SAMPLE_RATE)
                audio.writeframes(pcm)
            bytes_written, duration = self._validate_wav(temporary)
            try:
                os.link(temporary, destination)
            except FileExistsError:
                raise ProviderError("destination already exists", retryable=False) from None
            except OSError:
                if os.path.lexists(destination):
                    raise ProviderError("destination already exists", retryable=False) from None
                shutil.copy2(temporary, destination)
            temporary.unlink()
            temporary = None
        except ProviderError:
            raise
        except Exception:
            raise ProviderError("ElevenLabs returned invalid PCM audio", retryable=False) from None
        finally:
            if temporary is not None:
                with suppress(FileNotFoundError):
                    temporary.unlink()

        return SynthesisResult(
            request_id=request.request_id,
            duration_seconds=duration,
            bytes_written=bytes_written,
            provider_request_id=self._request_id(response_headers),
        )

    @staticmethod
    def _validate_pcm(pcm: bytes) -> None:
        if not isinstance(pcm, bytes) or not pcm or len(pcm) % _SAMPLE_WIDTH:
            raise ProviderError("ElevenLabs returned invalid PCM audio", retryable=False)
        if len(pcm) > _MAX_RESPONSE_BYTES:
            raise ProviderError("ElevenLabs audio response is too large", retryable=False)

    @staticmethod
    def _validate_wav(path: Path) -> tuple[int, float]:
        with wave.open(str(path), "rb") as audio:
            if (
                audio.getnchannels() != _CHANNELS
                or audio.getsampwidth() != _SAMPLE_WIDTH
                or audio.getframerate() != _SAMPLE_RATE
                or audio.getnframes() <= 0
            ):
                raise ValueError("invalid WAV")
            duration = audio.getnframes() / audio.getframerate()
        return path.stat().st_size, duration

    @staticmethod
    def _request_id(headers: Mapping[str, str]) -> str | None:
        lowered = {str(key).casefold(): value for key, value in headers.items()}
        value = lowered.get("request-id") or lowered.get("x-request-id")
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _http_post(
        url: str,
        body: bytes,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> tuple[bytes, Mapping[str, str]]:
        request = Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
                status = getattr(response, "status", 200)
                if not isinstance(status, int) or not 200 <= status < 300:
                    raise _HTTPStatusError(status if isinstance(status, int) else 500)
                audio = response.read(_MAX_RESPONSE_BYTES + 1)
                response_headers = dict(response.headers.items())
        except HTTPError as exc:
            raise _HTTPStatusError(exc.code) from None
        except URLError as exc:
            raise ConnectionError from exc
        return audio, response_headers

    @staticmethod
    def _provider_error(exc: BaseException) -> ProviderError:
        status = getattr(exc, "status", None)
        if not isinstance(status, int):
            status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            retryable = status in {408, 409, 429} or status >= 500
            if status in {401, 403}:
                message = "ElevenLabs authentication or permission failed"
            elif status == 429:
                message = "ElevenLabs rate limit or quota was reached"
            elif 400 <= status < 500:
                message = "ElevenLabs request was rejected"
            else:
                message = "ElevenLabs service request failed"
            return ProviderError(message, retryable=retryable)

        class_name = type(exc).__name__.casefold()
        retryable = (
            isinstance(exc, (TimeoutError, ConnectionError, asyncio.TimeoutError))
            or "timeout" in class_name
            or "connection" in class_name
            or "network" in class_name
        )
        return ProviderError(
            "ElevenLabs network request failed" if retryable else "ElevenLabs request failed",
            retryable=retryable,
        )


__all__ = ["ElevenLabsTTSProvider"]
