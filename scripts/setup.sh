#!/bin/sh
# Configure git hooks for this clone (and all its worktrees).
# Run once per clone after `git clone`.
#
# core.hooksPath is written to the clone's common config, so every
# worktree of this clone inherits it without re-running setup.

set -e

# Run from the repo root so `pre-commit install-hooks` finds
# .pre-commit-config.yaml regardless of where the script was invoked.
cd "$(git rev-parse --show-toplevel)"

if ! command -v pre-commit >/dev/null 2>&1; then
  cat >&2 <<'MSG'
Error: pre-commit not found on PATH.

Install via one of:
  pipx install pre-commit         # recommended (https://pypa.github.io/pipx/)
  brew install pre-commit         # macOS
  pip install --user pre-commit   # cross-platform

Docs: https://pre-commit.com/#install

After installation, re-run scripts/setup.sh
MSG
  exit 1
fi

git config core.hooksPath .githooks

# Install this repo's own console scripts (no-or-true-guard,
# release-notes-update) so they resolve on PATH — the no-or-true-guard
# local hook in .pre-commit-config.yaml uses `language: system`, which
# execs whatever's already on PATH rather than installing anything itself.
if ! python3 -m pip install --user -e . >/dev/null; then
  cat >&2 <<'MSG'
Error: failed to install this repo's console scripts (python3 -m pip install --user -e .).

no-or-true-guard depends on this being on PATH. Install manually via one of:
  python3 -m pip install --user -e .
  pipx install --editable . --force

Then re-run scripts/setup.sh.
MSG
  exit 1
fi

if ! command -v no-or-true-guard >/dev/null 2>&1; then
  user_base=$(python3 -m site --user-base 2>/dev/null || echo "$HOME/.local")
  cat >&2 <<MSG
Error: no-or-true-guard was installed but is not on PATH.

Add its install location to PATH, e.g.:
  export PATH="$user_base/bin:\$PATH"

Add that line to your shell profile (~/.bashrc, ~/.zshrc, etc.), then
re-run scripts/setup.sh.
MSG
  exit 1
fi

# Pre-populate hook environments so the first commit doesn't pay the
# install latency.
pre-commit install-hooks

cat <<'MSG'
Setup complete:
  - core.hooksPath = .githooks
  - hook environments cached for first commit

Hooks run on every commit (and gitleaks also on push), in this clone
and any of its worktrees. To bypass once (NOT recommended): commit
with --no-verify. To run hooks manually against the whole tree:
pre-commit run --all-files
MSG
