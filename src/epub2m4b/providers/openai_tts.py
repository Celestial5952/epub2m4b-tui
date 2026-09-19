"""OpenAI speech provider.

The SDK is intentionally imported only when a provider is actually used.  This
keeps construction and all unit tests independent of credentials and network
availability.
"""

from __future__ import annotations

import asyncio
import math
import os
import shutil
import uuid
import wave
from contextlib import suppress
from pathlib import Path
from typing import Any

from epub2m4b.exceptions import ProviderError
from epub2m4b.providers.base import SynthesisRequest, SynthesisResult


class OpenAITTSProvider:
    """TTSProvider adapter for the OpenAI speech endpoint."""

    name = "openai"
    _RESERVED_OPTIONS = frozenset(
        {
            "model",
            "voice",
            "input",
            "text",
            "speed",
            "instructions",
            "format",
            "response_format",
            "stream_format",
        }
    )

    def __init__(self, api_key: str, *, client: Any | None = None) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("OpenAI API key must be nonblank")
        self._api_key = api_key
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except Exception as exc:  # pragma: no cover - dependency packaging issue
                raise ProviderError("OpenAI provider is unavailable", retryable=False) from exc
            self._client = OpenAI(api_key=self._api_key)
        return self._client

    async def synthesize(self, request: SynthesisRequest, destination: Path) -> SynthesisResult:
        """Synthesize one WAV without blocking the event loop."""

        return await asyncio.to_thread(self._synthesize_sync, request, destination)

    async def check_model_access(self, model: str) -> str:
        """Verify authentication and model access without generating audio."""

        return await asyncio.to_thread(self._check_model_access_sync, model)

    def _check_model_access_sync(self, model: str) -> str:
        if not isinstance(model, str) or not model.strip():
            raise ProviderError("OpenAI model is required", retryable=False)
        try:
            response = self.client.models.retrieve(model)
        except ProviderError:
            raise
        except Exception as exc:
            raise self._provider_error(exc) from None
        returned = getattr(response, "id", None)
        if returned != model:
            raise ProviderError("OpenAI returned an unexpected model response", retryable=False)
        return returned

    def _synthesize_sync(self, request: SynthesisRequest, destination: Path) -> SynthesisResult:
        collisions = sorted(self._RESERVED_OPTIONS.intersection(request.options))
        if collisions:
            raise ProviderError(
                "request options conflict with required speech fields", retryable=False
            )
        if os.path.lexists(destination):
            raise ProviderError("destination already exists", retryable=False)

        destination = Path(destination)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            response = self.client.audio.speech.create(
                model=request.model,
                voice=request.voice,
                input=request.text,
                speed=request.speed,
                instructions=request.instructions,
                response_format="wav",
                **{
                    key: value
                    for key, value in request.options.items()
                    if key not in self._RESERVED_OPTIONS
                },
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise self._provider_error(exc) from None

        temporary: Path | None = None
        try:
            temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
            with temporary.open("xb"):
                pass
            self._write_response(response, temporary)
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
            raise ProviderError("OpenAI returned invalid WAV audio", retryable=False) from None
        finally:
            if temporary is not None:
                with suppress(FileNotFoundError):
                    temporary.unlink()

        return SynthesisResult(
            request_id=request.request_id,
            duration_seconds=duration,
            bytes_written=bytes_written,
            provider_request_id=self._response_request_id(response),
        )

    @staticmethod
    def _write_response(response: Any, destination: Path) -> None:
        writer = getattr(response, "write_to_file", None)
        if callable(writer):
            writer(str(destination))
            return
        content = getattr(response, "content", None)
        if not isinstance(content, (bytes, bytearray, memoryview)):
            raise ValueError("response did not contain audio bytes")
        destination.write_bytes(bytes(content))

    @staticmethod
    def _validate_wav(path: Path) -> tuple[int, float]:
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError("empty audio")
        with wave.open(str(path), "rb") as audio:
            frame_rate = audio.getframerate()
            frames = audio.getnframes()
            if frame_rate <= 0 or frames <= 0:
                raise ValueError("invalid audio duration")
            duration = frames / frame_rate
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError("invalid audio duration")
        return path.stat().st_size, duration

    @staticmethod
    def _response_request_id(response: Any) -> str | None:
        value = getattr(response, "_request_id", None)
        if value is None:
            value = getattr(response, "request_id", None)
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _provider_error(exc: BaseException) -> ProviderError:
        status = getattr(exc, "status", None)
        if not isinstance(status, int):
            status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            quota_codes = {
                "insufficient_quota",
                "quota_exceeded",
                "billing_hard_limit_reached",
            }
            message, error_type, code = OpenAITTSProvider._error_details(exc)
            quota_failure = isinstance(code, str) and code.lower() in quota_codes
            retryable = (
                status in {408, 409} or status >= 500 or status == 429
            ) and not quota_failure
            return ProviderError(
                "OpenAI request failed; "
                f"HTTP status={status}; "
                f"message={message}; "
                f"error_type={error_type}; "
                f"error_code={code}; "
                f"request_id={OpenAITTSProvider._error_request_id(exc)}",
                retryable=retryable,
            )

        class_name = type(exc).__name__.lower()
        retryable = (
            isinstance(exc, (TimeoutError, ConnectionError, asyncio.TimeoutError))
            or "timeout" in class_name
            or "connection" in class_name
            or "network" in class_name
        )
        return ProviderError(
            "OpenAI request failed; "
            "HTTP status=<absent>; "
            "message=<absent>; "
            f"error_type={type(exc).__name__}; "
            "error_code=<absent>; request_id=<absent>",
            retryable=retryable,
        )

    @staticmethod
    def _error_details(exc: BaseException) -> tuple[str, str, str]:
        """Return documented OpenAI error fields without serializing headers."""

        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            payload = body.get("error", body)
            if isinstance(payload, dict):
                message = payload.get("message", getattr(exc, "message", None))
                error_type = payload.get("type", getattr(exc, "type", None))
                code = payload.get("code", getattr(exc, "code", None))
                return (
                    message if isinstance(message, str) and message else "<absent>",
                    error_type if isinstance(error_type, str) and error_type else "<absent>",
                    str(code) if code is not None else "<absent>",
                )
        message = getattr(exc, "message", None)
        error_type = getattr(exc, "type", None)
        code = getattr(exc, "code", None)
        return (
            message if isinstance(message, str) and message else "<absent>",
            error_type if isinstance(error_type, str) and error_type else "<absent>",
            str(code) if code is not None else "<absent>",
        )

    @staticmethod
    def _error_request_id(exc: BaseException) -> str:
        request_id = getattr(exc, "request_id", None) or getattr(exc, "_request_id", None)
        if isinstance(request_id, str) and request_id:
            return request_id
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers is not None:
            get = getattr(headers, "get", None)
            if callable(get):
                request_id = get("x-request-id") or get("request-id")
                if isinstance(request_id, str) and request_id:
                    return request_id
        return "<absent>"
