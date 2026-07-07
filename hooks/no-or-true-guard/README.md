# no-or-true-guard

Pre-commit hook that blocks `|| true` and `|| :` from entering shell scripts,
GitHub Actions workflow/action YAML, Dockerfiles, and Makefiles.

## Usage in a consumer repo

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/Cure-HHT/hht_workflows
    rev: <tag containing no-or-true-guard>
    hooks:
      - id: no-or-true-guard
```

## What it does

Scans each staged file pre-commit routes to it (filtered to shell/yaml/dockerfile/makefile
via `types_or`) for the literal pattern `|| true` or `|| :`. Fails the commit and prints
every `path:line` match if any are found.

## Why this is banned

`|| true` (and `|| :`) silently swallows every failure mode of the command it follows —
network errors, auth failures, typos, real bugs — not just the one failure mode the author
intended to tolerate. The fix is always an explicit conditional that names what's tolerated
and why. See the root `~/.claude/CLAUDE.md` "Shell / Script Conventions" section for the
three accepted replacement forms.

## Why this lives here

`hooks/` in `cure-hht/hht_workflows` is reserved for Cure-HHT-specific pre-commit hooks
(see top-level `README.md`). This is the second hook here, after `release-notes-update`.
