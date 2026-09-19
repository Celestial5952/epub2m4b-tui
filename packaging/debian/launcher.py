"""Isolated entry point for the Debian private application directory."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
main = import_module("epub2m4b.cli").main

raise SystemExit(main())
