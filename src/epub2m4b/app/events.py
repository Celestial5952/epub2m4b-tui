from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    job_id: str
    chapter_index: int | None
    chunk_index: int | None
    completed_chunks: int
    total_chunks: int
    message: str
    output_path: str | None = None


@dataclass(frozen=True, slots=True)
class LogEvent:
    level: str
    operation: str
    message: str
    job_id: str | None = None
    chapter_index: int | None = None
    chunk_index: int | None = None
