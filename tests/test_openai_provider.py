import asyncio
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from epub2m4b.exceptions import ProviderError
from epub2m4b.providers import OpenAITTSProvider, SynthesisRequest


@pytest.fixture(autouse=True)
def synchronous_thread_runner(monkeypatch):
    """Keep filesystem-backed provider tests deterministic in the sandbox."""

    async def run(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", run)


def _wav() -> bytes:
    import io

    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8_000)
        audio.writeframes(b"\0\0" * 800)
    return output.getvalue()


class FakeSpeech:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _provider(response):
    speech = FakeSpeech(response)
    client = SimpleNamespace(audio=SimpleNamespace(speech=speech))
    return OpenAITTSProvider("sk-test-secret", client=client), speech


def _request():
    return SynthesisRequest(
        "Read this.", "gpt-test", "marin", 1.1, "Warmly", "req-7", {"temperature": 0.2}
    )


def test_payload_result_and_wav_validation(tmp_path):
    provider, speech = _provider(SimpleNamespace(content=_wav(), _request_id="remote-9"))
    destination = tmp_path / "speech.wav"

    result = asyncio.run(provider.synthesize(_request(), destination))

    payload = speech.calls[0]
    assert payload == {
        "model": "gpt-test",
        "voice": "marin",
        "input": "Read this.",
        "speed": 1.1,
        "instructions": "Warmly",
        "response_format": "wav",
        "temperature": 0.2,
    }
    assert result.request_id == "req-7"
    assert result.provider_request_id == "remote-9"
    assert result.bytes_written == destination.stat().st_size
    assert result.duration_seconds == 0.1
    with wave.open(str(destination), "rb") as audio:
        assert audio.getnframes() == 800


def test_write_to_file_response_is_supported(tmp_path):
    class Response:
        _request_id = "id"

        def write_to_file(self, path):
            Path(path).write_bytes(_wav())

    provider, _ = _provider(Response())
    destination = tmp_path / "speech.wav"
    asyncio.run(provider.synthesize(_request(), destination))
    assert destination.exists()


def test_synthesis_dispatches_sync_work_to_thread(tmp_path, monkeypatch):
    provider, _ = _provider(SimpleNamespace(content=_wav()))
    calls = []

    async def spy(func, *args, **kwargs):
        calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", spy)
    asyncio.run(provider.synthesize(_request(), tmp_path / "speech.wav"))
    assert calls == [provider._synthesize_sync]


def test_model_access_check_uses_unbilled_models_endpoint() -> None:
    models = SimpleNamespace(
        calls=[],
        retrieve=lambda model: models.calls.append(model) or SimpleNamespace(id=model),
    )
    client = SimpleNamespace(models=models)
    provider = OpenAITTSProvider("sk-test-secret", client=client)

    result = asyncio.run(provider.check_model_access("gpt-4o-mini-tts"))

    assert result == "gpt-4o-mini-tts"
    assert models.calls == ["gpt-4o-mini-tts"]


def test_model_access_check_reports_openai_error_details() -> None:
    class RemoteError(Exception):
        status_code = 401
        body = {
            "error": {
                "message": "Incorrect API key provided.",
                "type": "invalid_request_error",
                "code": "invalid_api_key",
            }
        }
        request_id = "req_connection_123"

    models = SimpleNamespace(retrieve=lambda model: (_ for _ in ()).throw(RemoteError()))
    provider = OpenAITTSProvider("sk-test-secret", client=SimpleNamespace(models=models))

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.check_model_access("gpt-4o-mini-tts"))

    assert "HTTP status=401" in str(caught.value)
    assert "error_code=invalid_api_key" in str(caught.value)
    assert "request_id=req_connection_123" in str(caught.value)


def test_existing_provider_error_is_not_rewrapped(tmp_path):
    provider, _ = _provider(SimpleNamespace())
    provider._client.audio.speech.create = lambda **kwargs: (_ for _ in ()).throw(
        ProviderError("provider is unavailable")
    )

    with pytest.raises(ProviderError, match="provider is unavailable") as caught:
        asyncio.run(provider.synthesize(_request(), tmp_path / "speech.wav"))

    assert not caught.value.retryable


@pytest.mark.parametrize(
    "option",
    [
        "model",
        "voice",
        "input",
        "text",
        "speed",
        "instructions",
        "format",
        "response_format",
        "stream_format",
    ],
)
def test_conflicting_options_are_rejected_before_client_call(tmp_path, option):
    provider, speech = _provider(SimpleNamespace(content=_wav()))
    request = SynthesisRequest(
        "Read this.", "gpt-test", "marin", 1.1, "Warmly", "req-7", {option: "bad"}
    )

    with pytest.raises(ProviderError, match="conflict") as caught:
        asyncio.run(provider.synthesize(request, tmp_path / "speech.wav"))
    assert not caught.value.retryable
    assert speech.calls == []


def test_invalid_wav_is_provider_error_and_does_not_leave_destination(tmp_path):
    provider, _ = _provider(SimpleNamespace(content=b"not wav"))
    destination = tmp_path / "speech.wav"

    with pytest.raises(ProviderError, match="invalid WAV") as caught:
        asyncio.run(provider.synthesize(_request(), destination))
    assert not caught.value.retryable
    assert not destination.exists()


def test_collision_is_rejected_without_request(tmp_path):
    provider, speech = _provider(SimpleNamespace(content=_wav()))
    destination = tmp_path / "speech.wav"
    destination.write_bytes(b"keep")

    with pytest.raises(ProviderError, match="already exists"):
        asyncio.run(provider.synthesize(_request(), destination))
    assert destination.read_bytes() == b"keep"
    assert speech.calls == []


@pytest.mark.parametrize(
    "status, retryable",
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
def test_status_classification_and_secret_redaction(tmp_path, status, retryable):
    secret = "sk-super-secret-value"

    class RemoteError(Exception):
        pass

    error = RemoteError(secret)
    error.status = status
    provider, _ = _provider(SimpleNamespace())
    provider._client.audio.speech.create = lambda **kwargs: (_ for _ in ()).throw(error)

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.synthesize(_request(), tmp_path / "speech.wav"))
    assert caught.value.retryable is retryable
    assert secret not in str(caught.value)


def test_openai_error_response_is_reported_with_request_id(tmp_path):
    class RemoteError(Exception):
        status_code = 400
        body = {
            "error": {
                "message": "Voice marin is unavailable for this model.",
                "type": "invalid_request_error",
                "code": "unsupported_voice",
            }
        }
        response = SimpleNamespace(headers={"x-request-id": "req_openai_123"})

    provider, _ = _provider(SimpleNamespace())
    provider._client.audio.speech.create = lambda **kwargs: (_ for _ in ()).throw(RemoteError())

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.synthesize(_request(), tmp_path / "speech.wav"))

    assert str(caught.value) == (
        "OpenAI request failed; HTTP status=400; "
        "message=Voice marin is unavailable for this model.; "
        "error_type=invalid_request_error; error_code=unsupported_voice; "
        "request_id=req_openai_123"
    )


def test_openai_error_does_not_serialize_authorization_header(tmp_path):
    class RemoteError(Exception):
        status = 401
        message = "Unauthorized"
        type = "authentication_error"
        code = "invalid_api_key"
        response = SimpleNamespace(headers={"Authorization": "Bearer sk-super-secret-value"})

    provider, _ = _provider(SimpleNamespace())
    provider._client.audio.speech.create = lambda **kwargs: (_ for _ in ()).throw(RemoteError())

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.synthesize(_request(), tmp_path / "speech.wav"))

    assert "Authorization" not in str(caught.value)
    assert "sk-super-secret-value" not in str(caught.value)


@pytest.mark.parametrize(
    "code", ["insufficient_quota", "quota_exceeded", "billing_hard_limit_reached"]
)
def test_quota_429_is_not_retryable(tmp_path, code):
    class RemoteError(Exception):
        status = 429

    error = RemoteError("do not expose")
    error.code = code
    provider, _ = _provider(SimpleNamespace())
    provider._client.audio.speech.create = lambda **kwargs: (_ for _ in ()).throw(error)

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.synthesize(_request(), tmp_path / "speech.wav"))
    assert not caught.value.retryable


@pytest.mark.parametrize(
    "error, retryable",
    [(TimeoutError(), True), (ConnectionError(), True), (ValueError("secret"), False)],
)
def test_network_classification_does_not_leak_exception_text(tmp_path, error, retryable):
    provider, _ = _provider(SimpleNamespace())
    provider._client.audio.speech.create = lambda **kwargs: (_ for _ in ()).throw(error)

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.synthesize(_request(), tmp_path / "speech.wav"))
    assert caught.value.retryable is retryable
    assert "error_type=" in str(caught.value)


def test_non_http_error_reports_safe_structured_diagnostics(tmp_path):
    provider, _ = _provider(SimpleNamespace())
    provider._client.audio.speech.create = lambda **kwargs: (_ for _ in ()).throw(
        RuntimeError("OpenAI client initialization failed")
    )

    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.synthesize(_request(), tmp_path / "speech.wav"))

    assert str(caught.value) == (
        "OpenAI request failed; HTTP status=<absent>; "
        "message=<absent>; "
        "error_type=RuntimeError; error_code=<absent>; request_id=<absent>"
    )


@pytest.mark.parametrize("key", ["", "   ", None])
def test_api_key_must_be_nonblank(key):
    with pytest.raises(ValueError):
        OpenAITTSProvider(key)


def test_synthesis_promotes_across_filesystems_when_link_fails(tmp_path, monkeypatch):
    import errno

    provider, _ = _provider(SimpleNamespace(content=_wav()))
    destination = tmp_path / "speech.wav"

    def fail_link(src, dst):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr("epub2m4b.providers.openai_tts.os.link", fail_link)
    result = asyncio.run(provider.synthesize(_request(), destination))

    assert destination.is_file()
    assert result.bytes_written == destination.stat().st_size

