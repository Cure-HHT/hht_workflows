# Cure-HHT custom pre-commit hooks

This directory holds pre-commit hooks specific to Cure-HHT conventions —
hooks that belong here rather than in a public pre-commit-hooks repository.
Each hook is a Python package under `hooks/<name>/` with its own README;
the `.pre-commit-hooks.yaml` manifest at the repo root declares each hook's
id, entry point, and stage.

| Hook | Stage | Purpose |
| --- | --- | --- |
| [`release-notes-update`](release-notes-update/) | pre-commit | Maintain per-PR release-notes fragments and consolidate them into `RELEASE_NOTES.md` |
| [`no-or-true-guard`](no-or-true-guard/) | pre-commit | Block the `\|\| true` / `\|\| :` shell short-circuit fallback |
| [`confidential-terms-scan`](confidential-terms-scan/) | pre-push | Scan added content, file/dir names, and branch name for confidential terms fetched at scan time from the consumer's `scan-*` Doppler project |

Consumer repos reference these hooks in their `.pre-commit-config.yaml` as
`repo: https://github.com/Cure-HHT/hht_workflows` (SHA- or tag-pinned) with
the relevant `hooks:` ID — see each hook's README for the exact block.
