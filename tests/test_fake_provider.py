import asyncio
import wave

from epub2m4b.providers import FakeTTSProvider, SynthesisRequest


def test_fake_provider_writes_valid_deterministic_wav(tmp_path) -> None:
    request = SynthesisRequest(
        text="A short offline test passage.",
        model="fake-model",
        voice="fake-voice",
        speed=1.0,
        instructions="Test only.",
        request_id="chunk-001",
    )
    first_path = tmp_path / "first.wav"
    second_path = tmp_path / "second.wav"

    first_provider = FakeTTSProvider()
    second_provider = FakeTTSProvider()
    first = asyncio.run(first_provider.synthesize(request, first_path))
    second = asyncio.run(second_provider.synthesize(request, second_path))

    assert first.duration_seconds == second.duration_seconds
    assert first_path.read_bytes() == second_path.read_bytes()
    assert first.bytes_written == first_path.stat().st_size
    with wave.open(str(first_path), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 8_000


def test_fake_provider_records_requests(tmp_path) -> None:
    provider = FakeTTSProvider()
    request = SynthesisRequest(
        text="Hello",
        model="fake-model",
        voice="fake-voice",
        speed=1.0,
        instructions="Test only.",
        request_id="request-42",
    )

    asyncio.run(provider.synthesize(request, tmp_path / "audio.wav"))

    assert provider.requests == [request]
