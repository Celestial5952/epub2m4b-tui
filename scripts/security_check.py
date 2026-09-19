"""Audit repository files to ensure no API keys or credentials are committed."""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Patterns that indicate real credentials/keys rather than synthetic test fixtures
_KEY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "OpenAI live API key",
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}\b"),
    ),
    (
        "ElevenLabs API key pattern",
        re.compile(
            r"\bxi-[A-Za-z0-9_\-]{20,}\b|"
            r"(?:elevenlabs|xi-api-key)[^\n]{0,20}['\"]([a-f0-9]{32})['\"]",
            re.IGNORECASE,
        ),
    ),
    (
        "Private Key header",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "GitHub token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    ),
]

_IGNORED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".runtime",
    "dist",
    ".agents",
    ".codex",
}

_IGNORED_FILES = {
    ".env",
    ".env.local",
    "Minecraft.deb",
}

# Known synthetic test values that are safe in test files
_SAFE_TEST_PREFIXES = (
    "sk-test-",
    "sk-sub-",
    "sk-saved-",
    "sk-super-",
    "sk-local-",
    "sk-new-",
    "xi-test-",
)


def load_local_secrets(repo_root: Path) -> list[str]:
    """Read local env files to get active secrets in-memory without exposing them."""
    secrets: list[str] = []
    for env_name in (".env.local", ".env"):
        env_file = repo_root / env_name
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            _, _, val = line.partition("=")
            clean_val = val.strip().strip("'\"").strip()
            # Only track secrets of sufficient length to avoid trivial false positives
            if len(clean_val) >= 12:
                secrets.append(clean_val)
    return secrets


def check_gitignore(repo_root: Path) -> list[str]:
    """Ensure sensitive patterns are present in .gitignore."""
    issues: list[str] = []
    gitignore_path = repo_root / ".gitignore"
    if not gitignore_path.is_file():
        issues.append(".gitignore file is missing")
        return issues

    content = gitignore_path.read_text(encoding="utf-8")
    required = [".env", ".env.*", ".runtime/", "dist/"]
    for req in required:
        if req not in content:
            issues.append(f".gitignore missing required pattern: {req}")
    return issues


def scan_files(repo_root: Path, known_secrets: list[str]) -> list[str]:
    """Scan all repo files for accidental secret leaks."""
    issues: list[str] = []

    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue

        # Skip ignored directories and files
        if any(part in _IGNORED_DIRS for part in path.parts):
            continue
        if path.name in _IGNORED_FILES or path.name.startswith(".env"):
            continue
        # Skip binary / media files
        if path.suffix in {".opus", ".wav", ".deb", ".epub", ".m4b", ".png", ".jpg", ".pyc"}:
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        lines = text.splitlines()
        for line_num, line in enumerate(lines, start=1):
            # Check 1: exact match against known active secrets
            for secret in known_secrets:
                if secret in line:
                    issues.append(
                        f"{path.relative_to(repo_root)}:{line_num} "
                        "[CRITICAL] Contains exact secret matching active local .env configuration!"
                    )

            # Check 2: pattern matching for live credential formats
            for label, pattern in _KEY_PATTERNS:
                for match_obj in pattern.finditer(line):
                    match_str = match_obj.group(0)
                    # Allow synthetic keys in test files
                    if any(match_str.startswith(prefix) for prefix in _SAFE_TEST_PREFIXES):
                        continue
                    # Allow documentation/manifest examples or redaction placeholders
                    if (
                        "<redacted>" in line
                        or "dummy" in line.lower()
                        or "example" in line.lower()
                    ):
                        continue
                    # Exclude the security check script itself from flagging its own patterns
                    if path.name == "security_check.py":
                        continue
                    issues.append(
                        f"{path.relative_to(repo_root)}:{line_num} "
                        f"[CRITICAL] Potential {label} detected."
                    )

    return issues


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    print(f"Running repository security check on {repo_root}...")

    issues: list[str] = []

    # 1. Verify .gitignore protection
    gitignore_issues = check_gitignore(repo_root)
    issues.extend(gitignore_issues)

    # 2. Extract local secrets in-memory (never logged)
    known_secrets = load_local_secrets(repo_root)
    print(f"Loaded {len(known_secrets)} active local secret(s) for in-memory matching.")

    # 3. Scan repo files
    scan_issues = scan_files(repo_root, known_secrets)
    issues.extend(scan_issues)

    if issues:
        print("\n❌ SECURITY ISSUES DETECTED:")
        for issue in issues:
            print(f"  - {issue}")
        print("\nPlease resolve these issues before committing or pushing to GitHub.")
        return 1

    print("\n✅ Security check passed: No API keys or credentials detected in repository files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
