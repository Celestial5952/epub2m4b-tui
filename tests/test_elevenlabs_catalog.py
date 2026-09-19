from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import pytest

from epub2m4b.exceptions import ProviderError
from epub2m4b.providers import ElevenLabsCatalog


@pytest.fixture(autouse=True)
def synchronous_thread_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", run)


class FakeGet:
    def __init__(self, payload: object = None, error: Exception | None = None) -> None:
        self.body = json.dumps(payload).encode() if payload is not None else b"{}"
        self.error = error
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def __call__(
        self, url: str, headers: dict[str, str], timeout: float
    ) -> tuple[bytes, dict[str, str]]:
        self.calls.append((url, dict(headers), timeout))
        if self.error is not None:
            raise self.error
        return self.body, {}


def test_list_voices_builds_explicit_query_and_parses_page() -> None:
    transport = FakeGet(
        {
            "voices": [
                {
                    "voice_id": "voice-2",
                    "name": "Ada",
                    "category": "premade",
                    "preview_url": "https://example.invalid/preview.mp3",
                },
                {"voice_id": "voice-1", "name": "Bert"},
            ],
            "has_more": True,
            "next_page_token": "page two",
        }
    )
    catalog = ElevenLabsCatalog("secret", transport=transport, timeout_seconds=9)

    page = asyncio.run(
        catalog.list_voices(search="narrator voice", page_size=25, next_page_token="first")
    )

    url, headers, timeout = transport.calls[0]
    assert url == (
        "https://api.elevenlabs.io/v2/voices?page_size=25&sort=name&"
        "sort_direction=asc&include_total_count=false&search=narrator+voice&"
        "next_page_token=first"
    )
    assert headers == {"Accept": "application/json", "xi-api-key": "secret"}
    assert timeout == 9
    assert [(voice.id, voice.name) for voice in page.voices] == [
        ("voice-2", "Ada"),
        ("voice-1", "Bert"),
    ]
    assert page.voices[0].category == "premade"
    assert page.voices[0].preview_url == "https://example.invalid/preview.mp3"
    assert page.voices[1].category is None
    assert page.has_more
    assert page.next_page_token == "page two"


def test_list_models_keeps_only_tts_models_and_provider_metadata() -> None:
    transport = FakeGet(
        [
            {
                "model_id": "eleven_multilingual_v2",
                "name": "Multilingual v2",
                "can_do_text_to_speech": True,
                "maximum_text_length_per_request": 10_000,
                "model_rates": {"character_cost_multiplier": 1.25},
            },
            {
                "model_id": "speech-to-text-only",
                "can_do_text_to_speech": False,
            },
            {
                "model_id": "tts-with-defaults",
                "can_do_text_to_speech": True,
            },
        ]
    )
    catalog = ElevenLabsCatalog("secret", transport=transport)

    models = asyncio.run(catalog.list_models())

    assert [model.id for model in models] == [
        "eleven_multilingual_v2",
        "tts-with-defaults",
    ]
    assert models[0].maximum_text_length == 10_000
    assert models[0].character_cost_multiplier == Decimal("1.25")
    assert models[1].name == "tts-with-defaults"
    assert models[1].maximum_text_length is None
    assert models[1].character_cost_multiplier is None
    assert transport.calls[0][0] == "https://api.elevenlabs.io/v1/models"


@pytest.mark.parametrize("page_size", [0, 101, True, 1.2])
def test_invalid_page_size_never_calls_provider(page_size: object) -> None:
    transport = FakeGet()
    catalog = ElevenLabsCatalog("secret", transport=transport)
    with pytest.raises(ValueError, match="page size"):
        asyncio.run(catalog.list_voices(page_size=page_size))  # type: ignore[arg-type]
    assert transport.calls == []


@pytest.mark.parametrize("field,value", [("search", ""), ("next_page_token", "  ")])
def test_invalid_optional_query_never_calls_provider(field: str, value: str) -> None:
    transport = FakeGet()
    catalog = ElevenLabsCatalog("secret", transport=transport)
    with pytest.raises(ValueError, match="nonblank"):
        asyncio.run(catalog.list_voices(**{field: value}))
    assert transport.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"voices": [], "has_more": True},
        {"voices": "bad", "has_more": False},
        {"voices": [{"voice_id": "", "name": "A"}], "has_more": False},
        {"voices": [{"voice_id": "v", "name": 7}], "has_more": False},
    ],
)
def test_invalid_voice_catalog_is_redacted(payload: object) -> None:
    catalog = ElevenLabsCatalog("secret", transport=FakeGet(payload))
    with pytest.raises(ProviderError, match="invalid voice catalog") as caught:
        asyncio.run(catalog.list_voices())
    assert not caught.value.retryable
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [{"model_id": "", "can_do_text_to_speech": True}],
        [
            {
                "model_id": "tts",
                "can_do_text_to_speech": True,
                "maximum_text_length_per_request": 0,
            }
        ],
        [
            {
                "model_id": "tts",
                "can_do_text_to_speech": True,
                "model_rates": {"character_cost_multiplier": -1},
            }
        ],
    ],
)
def test_invalid_model_catalog_is_redacted(payload: object) -> None:
    catalog = ElevenLabsCatalog("secret", transport=FakeGet(payload))
    with pytest.raises(ProviderError, match="invalid model catalog") as caught:
        asyncio.run(catalog.list_models())
    assert not caught.value.retryable
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("body", [b"", b"not json", b"\xff"])
def test_invalid_response_body_is_provider_error(body: bytes) -> None:
    transport = FakeGet()
    transport.body = body
    catalog = ElevenLabsCatalog("secret", transport=transport)
    with pytest.raises(ProviderError, match="invalid catalog"):
        asyncio.run(catalog.list_models())


@pytest.mark.parametrize(
    "status,retryable",
    [(401, False), (403, False), (422, False), (429, True), (500, True)],
)
def test_http_failures_are_classified_without_secret(
    status: int, retryable: bool
) -> None:
    secret = "catalog-secret"

    class RemoteError(Exception):
        pass

    error = RemoteError(secret)
    error.status = status  # type: ignore[attr-defined]
    catalog = ElevenLabsCatalog(secret, transport=FakeGet(error=error))
    with pytest.raises(ProviderError) as caught:
        asyncio.run(catalog.list_models())
    assert caught.value.retryable is retryable
    assert secret not in str(caught.value)


@pytest.mark.parametrize("key", ["", "  ", None])
def test_api_key_must_be_nonblank(key: str | None) -> None:
    with pytest.raises(ValueError):
        ElevenLabsCatalog(key)  # type: ignore[arg-type]
