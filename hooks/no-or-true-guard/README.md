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

## Known limitation: Comment and string-literal false positives

The guard scans raw file content by regex — it does not distinguish executable code from comments,
string literals, or documentation. If you need to reference the literal pattern in a comment or
doc string inside a shell/yaml/dockerfile/makefile file, reword to avoid the literal `|| true` or
`|| :` (e.g., write "OR-true" / "OR-colon" instead), exactly as this repo's own `.pre-commit-hooks.yaml`
file does when describing the guard in its `description:` field. There is currently no inline
ignore-pragma — that could be added in a future enhancement if the reword workaround proves
disruptive.

## Why this lives here

`hooks/` in `cure-hht/hht_workflows` is reserved for Cure-HHT-specific pre-commit hooks
(see top-level `README.md`). This is the second hook here, after `release-notes-update`.
