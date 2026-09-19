from __future__ import annotations

import wave
from pathlib import Path

from epub2m4b.providers.base import SynthesisRequest, SynthesisResult


class FakeTTSProvider:
    """Deterministic offline provider for tests and UI development."""

    name = "fake"

    def __init__(self, *, sample_rate: int = 8_000, characters_per_second: int = 40) -> None:
        if sample_rate <= 0 or characters_per_second <= 0:
            raise ValueError("fake provider rates must be greater than zero")
        self.sample_rate = sample_rate
        self.characters_per_second = characters_per_second
        self.requests: list[SynthesisRequest] = []

    async def synthesize(
        self,
        request: SynthesisRequest,
        destination: Path,
    ) -> SynthesisResult:
        self.requests.append(request)
        duration = max(0.1, len(request.text) / self.characters_per_second)
        frame_count = round(self.sample_rate * duration)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(destination), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(self.sample_rate)
            output.writeframes(b"\x00\x00" * frame_count)
        return SynthesisResult(
            request_id=request.request_id,
            duration_seconds=frame_count / self.sample_rate,
            bytes_written=destination.stat().st_size,
            provider_request_id=f"fake-{request.request_id}",
        )
