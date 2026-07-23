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
REPO_ROOT="$(pwd)"

# --check: report, through exit status, whether this clone is already in the
# state a plain `scripts/setup.sh` produces — without changing anything. The
# hooks-path test reuses the shared guard's predicate so it agrees with the
# developer-facing warning (absolute core.hooksPath resolved, not string-matched).
# Implements: HHT-OPS-repo-bootstrap/B
if [ "${1:-}" = "--check" ]; then
  . "$REPO_ROOT/bootstrap/hooks-guard.sh"
  rc=0
  if hht_hooks_active "$REPO_ROOT" ".githooks"; then
    echo "ok: core.hooksPath points at this repo's .githooks"
  else
    echo "not set up: core.hooksPath does not point at .githooks — run scripts/setup.sh" >&2
    rc=1
  fi
  if command -v pre-commit >/dev/null 2>&1; then
    echo "ok: pre-commit on PATH"
  else
    echo "not set up: pre-commit not on PATH — run scripts/setup.sh" >&2
    rc=1
  fi
  if command -v no-or-true-guard >/dev/null 2>&1; then
    echo "ok: repo console scripts on PATH (no-or-true-guard)"
  else
    echo "not set up: repo console scripts missing from PATH (no-or-true-guard) — run scripts/setup.sh" >&2
    rc=1
  fi
  exit "$rc"
fi

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

# Claude Code tooling: the governance gate (/admin-review), the PR-workflow
# commands, and the hooks guarding PR merges and worktree deletion.
# Installed at user scope, so it applies to every Claude Code session
# on this machine -- see plugins/hht-devkit/README.md in Cure-HHT/hht_admin
# (https://github.com/Cure-HHT/hht_admin).
#
# This repo is PUBLIC and the plugin lives in the private Cure-HHT/hht_admin
# (the governance gate greps for sponsor codenames by name, which bars it from
# a public host). An outside clone therefore cannot fetch it, and does not need
# to: the checks that matter here are enforced in CI. The install is optional,
# so failure is a warning rather than a setup failure.
if ! command -v claude >/dev/null 2>&1; then
  echo
  echo "Note: claude CLI not found; skipped the optional hht-devkit plugin."
elif claude plugin marketplace add Cure-HHT/hht_admin \
       --scope user --sparse .claude-plugin plugins >/dev/null 2>&1 ||
     claude plugin marketplace update hht-admin >/dev/null; then
  if claude plugin install hht-devkit@hht-admin --scope user >/dev/null &&
     claude plugin update hht-devkit@hht-admin >/dev/null; then
    echo
    echo "Installed the hht-devkit Claude Code plugin (user scope): the"
    echo "governance gate, the PR-workflow commands, and hooks guarding PR"
    echo "merges and worktree deletion. These apply to ALL"
    echo "Claude Code sessions on this machine."
    echo "  Opt out with: claude plugin disable hht-devkit"
  else
    echo "Warning: hht-devkit plugin install/update failed; run by hand:" >&2
    echo "  claude plugin install hht-devkit@hht-admin --scope user" >&2
    echo "  claude plugin update hht-devkit@hht-admin" >&2
  fi
else
  echo
  echo "Note: skipped the hht-devkit Claude Code plugin -- could not add or"
  echo "  refresh the hht-admin marketplace. Optional here; it lives in the"
  echo "  private Cure-HHT/hht_admin and needs access."
fi
