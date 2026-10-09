from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from epub2m4b.app.runtime import LocalApplicationService
from epub2m4b.estimate_cli import run_estimate
from epub2m4b.tui import EPUB2M4BApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="epub2m4b",
        description="Convert EPUB ebooks into chaptered M4B audiobooks.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    commands = parser.add_subparsers(dest="command", metavar="command")
    estimate = commands.add_parser(
        "estimate",
        help="estimate text size and narration cost for an EPUB or a folder of EPUBs",
        description=(
            "Measure one EPUB, or every EPUB in a folder, and print characters, "
            "words, audio length, and estimated cost for each supported provider. "
            "Works entirely offline: no network request is made and no API key is read."
        ),
    )
    estimate.add_argument("path", type=Path, help="an .epub file or a folder containing them")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "estimate":
        return run_estimate(args.path, sys.stdout, sys.stderr)
    service = LocalApplicationService.create_default()
    EPUB2M4BApp(service).run()
    return 0
