from __future__ import annotations

import sys
from pathlib import Path

# Ensure scripts can be imported
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.security_check import check_gitignore, load_local_secrets, scan_files


def test_gitignore_protects_sensitive_files() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    issues = check_gitignore(repo_root)
    assert not issues, f"Gitignore issues: {issues}"


def test_repository_contains_no_secrets() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    known_secrets = load_local_secrets(repo_root)
    issues = scan_files(repo_root, known_secrets)
    assert not issues, "Secret leaks detected in repository:\n" + "\n".join(issues)


def test_security_scanner_detects_synthetic_leak(tmp_path: Path) -> None:
    fake_root = tmp_path / "repo"
    fake_root.mkdir()
    leaked_file = fake_root / "leaked.py"
    dummy_key = "sk-proj-" + "1234567890abcdef1234567890abcdef12"
    leaked_file.write_text(f"API_KEY = '{dummy_key}'\n", encoding="utf-8")

    issues = scan_files(fake_root, ["dummy-secret-12345"])
    assert any("OpenAI live API key" in issue for issue in issues)


def test_security_scanner_detects_known_env_secret(tmp_path: Path) -> None:
    fake_root = tmp_path / "repo"
    fake_root.mkdir()
    leaked_file = fake_root / "config.json"
    leaked_file.write_text('{"secret": "my-secret-token-12345"}\n', encoding="utf-8")

    issues = scan_files(fake_root, ["my-secret-token-12345"])
    assert any("Contains exact secret" in issue for issue in issues)
