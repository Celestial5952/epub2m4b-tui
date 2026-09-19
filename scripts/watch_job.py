#!/usr/bin/env python3
"""Render a read-only progress bar for one EPUB2M4B job manifest."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--title", default="EPUB2M4B")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    width = 48
    while True:
        try:
            data = json.loads(args.manifest.read_text(encoding="utf-8"))
            chunks = data.get("chunks", [])
            complete = sum(chunk.get("status") == "complete" for chunk in chunks)
            total = len(chunks)
            fraction = complete / total if total else 0.0
            filled = round(width * fraction)
            bar = "█" * filled + "░" * (width - filled)
            status = str(data.get("status", "unknown")).upper()
            output_ready = bool(args.output and args.output.is_file())
            print("\033[2J\033[H", end="")
            print(f"{args.title}\n")
            print(f"[{bar}] {fraction:6.1%}")
            print(f"\nChunks: {complete} / {total}")
            print(f"Status: {status}")
            print(f"M4B: {'ready' if output_ready else 'waiting for assembly'}")
            print("\nThis display is read-only. Ctrl+C closes it without stopping generation.")
            if output_ready and status == "COMPLETE":
                return 0
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            print("\033[2J\033[HWaiting for readable job progress…", end="", flush=True)
        time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
