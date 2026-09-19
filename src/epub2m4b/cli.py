from __future__ import annotations

import argparse
from collections.abc import Sequence

from epub2m4b.app.runtime import LocalApplicationService
from epub2m4b.tui import EPUB2M4BApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="epub2m4b",
        description="Convert EPUB ebooks into chaptered M4B audiobooks.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    service = LocalApplicationService.create_default()
    EPUB2M4BApp(service).run()
    return 0
