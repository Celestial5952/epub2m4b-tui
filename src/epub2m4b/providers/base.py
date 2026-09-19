from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class SynthesisRequest:
    text: str
    model: str
    voice: str
    speed: float
    instructions: str
    request_id: str
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("synthesis text cannot be empty")
        if self.speed <= 0:
            raise ValueError("synthesis speed must be greater than zero")


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    request_id: str
    duration_seconds: float
    bytes_written: int
    provider_request_id: str | None = None


class TTSProvider(Protocol):
    name: str

    async def synthesize(
        self,
        request: SynthesisRequest,
        destination: Path,
    ) -> SynthesisResult: ...
