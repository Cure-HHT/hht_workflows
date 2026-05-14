# release-notes-update

Pre-commit hook that maintains per-PR release-notes fragments and consolidates them into `RELEASE_NOTES.md`.

## Usage in a consumer repo

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/Cure-HHT/hht_workflows
    rev: <release-notes-update-vX.Y.Z>
    hooks:
      - id: release-notes-update
        args:
          - --version-command=cat VERSION       # or `yq '.version' pubspec.yaml`, etc.
```

## What it does

On every commit:

1. Reads the current version from the configured `--version-command`.
2. Refreshes the fragment for the current branch at `.release-notes/<branch-slug>.md` from `git log merge-base..HEAD --pretty=%s`, keeping only commits whose subject starts with `[CUR-XXX]`.
3. Consolidates any fragments on `origin/main` not yet represented in `RELEASE_NOTES.md` into their respective version sections, then removes those fragments.
4. Re-stages the modified files so they land in the dev's commit.

The hook does not call any LLM, post anywhere, or fetch over the network. It only reads `origin/main` as it currently exists locally.

## What it doesn't do

- It does not amend or push commits. All changes are staged for the dev to commit normally.
- It does not generate the human-readable Claude summary. That's a separate `pre-push` hook (PR 2).
- It does not enforce that consumers have a `RELEASE_NOTES.md`; if missing, it creates one with the header.

## Why this lives here

`hooks/` in `cure-hht/hht_workflows` is reserved for Cure-HHT-specific pre-commit hooks (see top-level `README.md`). This is the first such hook.
