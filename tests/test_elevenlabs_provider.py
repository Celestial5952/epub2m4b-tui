from __future__ import annotations

import asyncio
import json
import wave
from pathlib import Path

import pytest

from epub2m4b.exceptions import ProviderError
from epub2m4b.providers import ElevenLabsTTSProvider, SynthesisRequest


@pytest.fixture(autouse=True)
def synchronous_thread_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", run)


class FakeTransport:
    def __init__(
        self,
        pcm: bytes = b"\0\0" * 2_400,
        headers: dict[str, str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.pcm = pcm
        self.headers = headers or {}
        self.error = error
        self.calls: list[tuple[str, bytes, dict[str, str], float]] = []

    def __call__(
        self,
        url: str,
        body: bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> tuple[bytes, dict[str, str]]:
        self.calls.append((url, body, dict(headers), timeout))
        if self.error is not None:
            raise self.error
        return self.pcm, self.headers


def _request(**changes: object) -> SynthesisRequest:
    values = {
        "text": "Read this.",
        "model": "eleven_multilingual_v2",
        "voice": "voice /?",
        "speed": 1.1,
        "instructions": "Warmly",
        "request_id": "req-7",
        "options": {"seed": 17, "voice_settings": {"stability": 0.6}},
    }
    values.update(changes)
    return SynthesisRequest(**values)  # type: ignore[arg-type]


def test_payload_pcm_wrapping_and_result(tmp_path: Path) -> None:
    transport = FakeTransport(headers={"Request-Id": "remote-9"})
    provider = ElevenLabsTTSProvider(
        "eleven-test-secret", transport=transport, timeout_seconds=12.5
    )
    destination = tmp_path / "speech.wav"

    result = asyncio.run(provider.synthesize(_request(), destination))

    url, body, headers, timeout = transport.calls[0]
    assert url == (
        "https://api.elevenlabs.io/v1/text-to-speech/voice%20%2F%3F"
        "?output_format=pcm_24000"
    )
    assert json.loads(body) == {
        "text": "Read this.",
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.6, "speed": 1.1},
        "seed": 17,
    }
    assert headers == {
        "Accept": "audio/pcm",
        "Content-Type": "application/json",
        "xi-api-key": "eleven-test-secret",
    }
    assert timeout == 12.5
    assert result.request_id == "req-7"
    assert result.provider_request_id == "remote-9"
    assert result.bytes_written == destination.stat().st_size
    assert result.duration_seconds == pytest.approx(0.1)
    with wave.open(str(destination), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 24_000
        assert audio.getnframes() == 2_400


def test_synthesis_dispatches_sync_work_to_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ElevenLabsTTSProvider("key", transport=FakeTransport())
    calls = []

    async def spy(func, *args, **kwargs):
        calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", spy)
    asyncio.run(provider.synthesize(_request(), tmp_path / "speech.wav"))
    assert calls == [provider._synthesize_sync]


@pytest.mark.parametrize("option", ["text", "model_id", "voice_id", "output_format"])
def test_reserved_options_are_rejected_before_transport(tmp_path: Path, option: str) -> None:
    transport = FakeTransport()
    provider = ElevenLabsTTSProvider("key", transport=transport)

    with pytest.raises(ProviderError, match="conflict") as caught:
        asyncio.run(
            provider.synthesize(
                _request(options={option: "bad"}), tmp_path / "speech.wav"
            )
        )
    assert not caught.value.retryable
    assert transport.calls == []


def test_conflicting_speed_is_rejected_before_transport(tmp_path: Path) -> None:
    transport = FakeTransport()
    provider = ElevenLabsTTSProvider("key", transport=transport)
    request = _request(options={"voice_settings": {"speed": 0.8}})

    with pytest.raises(ProviderError, match="speed conflicts"):
        asyncio.run(provider.synthesize(request, tmp_path / "speech.wav"))
    assert transport.calls == []


@pytest.mark.parametrize("pcm", [b"", b"\0"])
def test_invalid_pcm_is_rejected_without_destination(tmp_path: Path, pcm: bytes) -> None:
    destination = tmp_path / "speech.wav"
    provider = ElevenLabsTTSProvider("key", transport=FakeTransport(pcm=pcm))

    with pytest.raises(ProviderError, match="invalid PCM") as caught:
        asyncio.run(provider.synthesize(_request(), destination))
    assert not caught.value.retryable
    assert not destination.exists()


def test_collision_is_rejected_without_transport(tmp_path: Path) -> None:
    destination = tmp_path / "speech.wav"
    destination.write_bytes(b"keep")
    transport = FakeTransport()
    provider = ElevenLabsTTSProvider("key", transport=transport)

    with pytest.raises(ProviderError, match="already exists"):
        asyncio.run(provider.synthesize(_request(), destination))
    assert destination.read_bytes() == b"keep"
    assert transport.calls == []


@pytest.mark.parametrize(
    "status,retryable",
    [
        (408, True),
        (409, True),
        (429, True),
        (500, True),
        (503, True),
        (400, False),
        (401, False),
        (403, False),
        (404, False),
        (422, False),
    ],
)
def test_status_classification_and_secret_redaction(
    tmp_path: Path, status: int, retryable: bool
) -> None:
    secret = "eleven-super-secret-value"

    class RemoteError(Exception):
        pass

    error = RemoteError(secret)
    error.status = status  # type: ignore[attr-defined]
    provider = ElevenLabsTTSProvider(secret, transport=FakeTransport(error=error))

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.synthesize(_request(), tmp_path / "speech.wav"))
    assert caught.value.retryable is retryable
    assert secret not in str(caught.value)


@pytest.mark.parametrize(
    "error,retryable",
    [(TimeoutError(), True), (ConnectionError(), True), (ValueError("secret"), False)],
)
def test_network_classification_does_not_leak_exception_text(
    tmp_path: Path, error: Exception, retryable: bool
) -> None:
    provider = ElevenLabsTTSProvider("key", transport=FakeTransport(error=error))

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.synthesize(_request(), tmp_path / "speech.wav"))
    assert caught.value.retryable is retryable
    assert "secret" not in str(caught.value)


def test_non_json_options_are_rejected_before_transport(tmp_path: Path) -> None:
    transport = FakeTransport()
    provider = ElevenLabsTTSProvider("key", transport=transport)

    with pytest.raises(ProviderError, match="JSON"):
        asyncio.run(
            provider.synthesize(
                _request(options={"seed": object()}), tmp_path / "speech.wav"
            )
        )
    assert transport.calls == []


@pytest.mark.parametrize("key", ["", "   ", None])
def test_api_key_must_be_nonblank(key: str | None) -> None:
    with pytest.raises(ValueError):
        ElevenLabsTTSProvider(key)  # type: ignore[arg-type]


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_timeout_must_be_finite_and_positive(timeout: float) -> None:
    with pytest.raises(ValueError):
        ElevenLabsTTSProvider("key", timeout_seconds=timeout)


def test_synthesis_promotes_across_filesystems_when_link_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    provider = ElevenLabsTTSProvider("key", transport=FakeTransport())
    destination = tmp_path / "speech.wav"

    def fail_link(src: str | Path, dst: str | Path) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr("epub2m4b.providers.elevenlabs_tts.os.link", fail_link)
    result = asyncio.run(provider.synthesize(_request(), destination))

    assert destination.is_file()
    assert result.bytes_written == destination.stat().st_size

