#!/usr/bin/env python3
"""Resume one explicitly authorized EPUB-to-M4B production run."""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from epub2m4b.audio.m4b import assemble_m4b  # noqa: E402
from epub2m4b.audio.tools import probe_duration  # noqa: E402
from epub2m4b.config import DEFAULT_INSTRUCTIONS  # noqa: E402
from epub2m4b.epub.cover import read_cover  # noqa: E402
from epub2m4b.generation.cache import AudioCache  # noqa: E402
from epub2m4b.generation.coordinator import GenerationCoordinator  # noqa: E402
from epub2m4b.generation.estimate import TTSPricing, estimate_narration  # noqa: E402
from epub2m4b.generation.job import PreparedJob, prepare_job  # noqa: E402
from epub2m4b.generation.manifest import ManifestRepository  # noqa: E402
from epub2m4b.models import JobManifest, NarrationSettings  # noqa: E402
from epub2m4b.providers.openai_tts import OpenAITTSProvider  # noqa: E402


class ProgressProvider:
    """Print non-secret progress while delegating synthesis."""

    name = "openai"

    def __init__(self, provider: OpenAITTSProvider, total: int) -> None:
        self.provider = provider
        self.total = total
        self.started = 0

    async def synthesize(self, request, destination):  # type: ignore[no-untyped-def]
        self.started += 1
        print(
            f"synthesizing {self.started}/{self.total}: {request.request_id}",
            flush=True,
        )
        return await self.provider.synthesize(request, destination)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("job_directory", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--authorized-max-cost", type=Decimal, required=True)
    parser.add_argument("--voice", default="marin")
    parser.add_argument("--model", default="gpt-4o-mini-tts")
    parser.add_argument("--bitrate-kbps", type=int, default=96)
    parser.add_argument("--env-file", type=Path)
    return parser.parse_args()


def _prepare(args: argparse.Namespace) -> PreparedJob:
    settings = NarrationSettings(
        provider="openai",
        model=args.model,
        voice=args.voice,
        speed=1.0,
        instructions=DEFAULT_INSTRUCTIONS,
    )
    return prepare_job(
        args.source,
        settings,
        job_id="lenin-what-is-to-be-done",
        app_version="0.1.0",
        timestamp=datetime.now(UTC),
    )


def _load_or_create_manifest(path: Path, prepared: PreparedJob) -> JobManifest:
    if path.exists():
        saved = ManifestRepository.load(path)
        if saved.source.sha256 != prepared.manifest.source.sha256:
            raise RuntimeError("saved job source does not match the requested EPUB")
        expected_hashes = tuple(chunk.generation_hash for chunk in prepared.chunks)
        saved_hashes = tuple(chunk.generation_hash for chunk in saved.chunks)
        if saved_hashes != expected_hashes:
            raise RuntimeError("saved job narration settings or chunking do not match")
        return saved
    ManifestRepository.save(path, prepared.manifest)
    return prepared.manifest


def _api_key(env_file: Path | None) -> str:
    configured = os.environ.get("OPENAI_API_KEY", "")
    if configured or env_file is None:
        return configured
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        name, separator, value = line.partition("=")
        if separator and name.strip() == "OPENAI_API_KEY":
            values = shlex.split(value, comments=False, posix=True)
            return values[0] if len(values) == 1 else ""
    return ""


async def _run(args: argparse.Namespace) -> None:
    if args.authorized_max_cost <= 0:
        raise RuntimeError("authorized maximum cost must be positive")
    prepared = _prepare(args)
    pricing = TTSPricing("0.60", "12.00", "20")
    estimate = estimate_narration(
        prepared.chunks,
        pricing,
        words_per_minute="120",
        safety_multiplier="1.15",
    )
    print(
        f"prepared {len(prepared.book.chapters)} chapters / {len(prepared.chunks)} chunks; "
        f"guarded estimate ${estimate.estimated_cost_usd}",
        flush=True,
    )
    if estimate.estimated_cost_usd > args.authorized_max_cost:
        raise RuntimeError("guarded estimate exceeds the explicitly authorized cost cap")

    api_key = _api_key(args.env_file)
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured in the process environment")
    args.job_directory.mkdir(parents=True, exist_ok=True)
    manifest_path = args.job_directory / "manifest.json"
    manifest = _load_or_create_manifest(manifest_path, prepared)
    remaining = sum(1 for chunk in manifest.chunks if not chunk.audio_path)
    provider = ProgressProvider(OpenAITTSProvider(api_key), max(remaining, 1))
    coordinator = GenerationCoordinator(
        provider,
        AudioCache(args.job_directory / "cache"),
        validator=lambda path: probe_duration(path) > 0,
        duration_reader=probe_duration,
        max_attempts=5,
    )
    result = await coordinator.run(manifest_path)
    print(
        f"generation complete: {result.synthesized_chunks} synthesized, "
        f"{result.recovered_chunks} recovered",
        flush=True,
    )
    titles = {chapter.index: chapter.title for chapter in prepared.book.chapters}
    assembly = assemble_m4b(
        result.manifest,
        titles,
        args.destination,
        bitrate_kbps=args.bitrate_kbps,
        cover=read_cover(args.source),
    )
    print(
        f"M4B complete: {assembly.path} ({assembly.duration_seconds / 3600:.2f} hours, "
        f"{assembly.size_bytes} bytes, {len(assembly.chapters)} chapters)",
        flush=True,
    )


def main() -> int:
    try:
        asyncio.run(_run(_arguments()))
    except Exception as exc:
        print(f"run stopped safely: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
