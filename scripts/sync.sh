#!/usr/bin/env bash
set -euo pipefail

# EPUB2M4B GitHub Sync Script
# Audits secrets, commits safe changes, and pushes to remote.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

echo "🔒 Running pre-sync security check..."
if ! .venv/bin/python scripts/security_check.py; then
    echo "❌ Security check failed! Aborting sync to protect credentials." >&2
    exit 1
fi

# Check for uncommitted changes
if ! git diff-index --quiet HEAD -- || [ -n "$(git status --porcelain)" ]; then
    COMMIT_MSG="${1:-Auto-sync checkpoint: $(date -u +"%Y-%m-%dT%H:%M:%SZ")}"
    echo "💾 Staging safe changes and creating commit..."
    git add -A
    git commit -m "${COMMIT_MSG}"
else
    echo "✨ Working tree is already clean. Nothing new to commit."
fi

# Check if origin remote exists
if git remote get-url origin >/dev/null 2>&1; then
    CURRENT_BRANCH="$(git branch --show-current)"
    echo "🚀 Pushing branch '${CURRENT_BRANCH}' to origin..."
    git push -u origin "${CURRENT_BRANCH}"
    echo "✅ Successfully synced to GitHub!"
else
    echo "ℹ️  No 'origin' remote is configured yet."
    echo "   Once you have a GitHub repository, connect it by running:"
    echo "     git remote add origin git@github.com:<your-username>/<repo-name>.git"
    echo "     git push -u origin $(git branch --show-current)"
fi
