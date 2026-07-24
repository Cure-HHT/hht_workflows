# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`cure-hht/hht_workflows` is a **public** library of GitHub Actions composite actions and pre-commit hooks consumed by other Cure-HHT repos (public and private). Composite actions are invoked via `uses: Cure-HHT/hht_workflows/.github/actions/<name>@<ref>`; pre-commit hooks are installed via `repo: https://github.com/Cure-HHT/hht_workflows` in consumer `.pre-commit-config.yaml` files. Most PRs change a composite action under `.github/actions/<name>/action.yml`, a pre-commit hook under `hooks/<name>/`, or one of the workflows that exercises them. Confidential infrastructure (Terraform, customer-identifying config) lives in the separate private `cure-hht/hht_admin` repo.

## High-level architecture

### Composite action + thin wrapper, dogfooded

For every composite action there is a **canonical implementation** at `.github/actions/<name>/action.yml` (the artifact consumers `uses:`) and, where the action emits a required status check, a **thin dogfood wrapper** at `.github/workflows/<name>.yml` that invokes the local copy via `uses: ./.github/actions/<name>` so this repo's own PRs are gated by the same logic consumers will run.

Critical convention: the wrapper's job `name:` field becomes the check-context name GitHub stores against the commit. Branch protection matches by that **bare job name** (not the `<workflow> / <job>` form the UI shows). When adding a new required-check action, the wrapper's `jobs.<x>.name:` must exactly equal the name the org-level ruleset expects.

### Readiness checks are the per-action PR gate

`.github/workflows/readiness-checks.yml` is the canonical place to add a real end-to-end happy-path job for each action that has environmental prerequisites (WIF binding, OIDC handshake, etc.). Each readiness job's bare name is wired into `main`'s required-status-checks list (see `docs/branch-protection.md`). Adding a new action with external-dependency wiring → add a corresponding readiness job → add its bare name to the protection list.

### Two trigger types, deliberately

Workflows trigger on both `pull_request` and (limited) `push: branches: [main]`. Without the `branches:` filter, both triggers fire for the same feature-branch commit and GitHub disambiguates the check name with `(push)` / `(pull_request)` suffixes — which would prevent the bare check name from ever resolving against branch protection. Restricting push to `main` only is intentional; preserve it when editing these workflows.

### Validation Summary is a meta-check

`validation-summary` polls all other check runs on the PR head commit, waits up to 30 minutes for them to finalize, and emits a single PASS/FAIL plus an upserted PR comment. It is the aggregate required-context the org ruleset depends on so the list of "real" required checks can evolve without touching org config every time. Its trigger types **must** mirror those of every check it supervises (notably `edited` for PR-title re-validation on title/body edits).

### Release-notes pipeline (deterministic half — PR 1)

`hooks/release-notes-update/` is a pre-commit hook that maintains per-PR fragments at `.release-notes/<branch-slug>.md` and consolidates them into a versioned `RELEASE_NOTES.md` in the consumer repo. `.github/actions/release-notes-publish/` is the **read-only** CI counterpart: at publish time it slices the top section + any pending matching-version fragments and emits the result as step outputs for `slack-notify` to consume. Critical contract: **CI never writes to the repo**. All file mutation lives in the dev's pre-commit hook (no bot pushes, no `--no-verify` bypass of branch protection). PR 2 will add a pre-push hook that runs `claude -p` to populate the `<!-- summary --> ... <!-- /summary -->` block.

## Common commands

After cloning (per clone, not per worktree):

```sh
scripts/setup.sh                  # sets core.hooksPath=.githooks and warms pre-commit cache
```

Requires `pre-commit` on PATH (`pipx install pre-commit` recommended).

Local linting / scanning (mirrors what runs in CI):

```sh
pre-commit run --all-files        # all hooks
pre-commit run gitleaks           # one hook
pre-commit run actionlint         # validate workflows/action YAML
pre-commit run markdownlint       # markdown lint (ignores .github/)
```

Python tests (`release-notes-update` hook + `release-notes-publish` action):

```sh
pip install -e '.[test]'                                                  # from repo root, once
pytest hooks/release-notes-update/tests/ -v                               # hook tests (25 cases)
(cd .github/actions/release-notes-publish && \
  PYTHONPATH=.:../../../hooks/release-notes-update pytest tests/ -v)      # publish action tests (4 cases)
```

Bypass (avoid — gitleaks runs at pre-commit AND pre-push as the last line of defense):

```sh
git commit --no-verify
```

There is no build/test runner — `actionlint` is the static validator for the actual artifacts (`.github/actions/**/action.yml`, `.github/workflows/**.yml`). Runtime verification of an action happens via its readiness-checks job on a PR.

## Cross-repo requirement citations

`spec/` citations that name another Cure-HHT repo's REQ (e.g. `HHT-OPS-*`)
resolve only when that repo is linked as an elspais associate. If
`elspais checks` reports broken references, run:

```sh
elspais associate --all
```

This is machine-local (`.elspais.local.toml`, git-ignored) and does not survive
a clone — `scripts/setup.sh` re-runs it. CI does the equivalent via the
`elspais-federate` action. See `HHT-OPS-repo-bootstrap/I` in hht_admin.

## Conventions that bite if missed

- **PR titles**: must contain `[CUR-XXX]` (Linear issue ref) or `[Dependabot]`. Squash-merges use the PR title verbatim as the `main` commit subject, so this guards downstream traceability. The `validate-pr-title` action enforces it.
- **SHA-pin third-party actions**: composite actions in this repo wrap upstream actions (e.g. `google-github-actions/auth`, `dopplerhq/secrets-fetch-action`) at a specific commit SHA, not by tag or branch. Centralizing the pin here is the point of the library — upgrades land in one place.
- **Consumers SHA-pin**: documented in `README.md`. Consumers reference actions by full commit SHA (`@<40-char-sha>`), never `@main` or a moving tag, so no unreviewed change reaches them automatically (`HHT-OPS-composite-action-library/B`). Within this repo's own wrappers we use `./.github/actions/<name>` (path) so dogfood checks always run against the PR's version, not against `main`.
- **Repo-wide release tags**: releases are repo-wide SemVer tags (`vX.Y.Z` immutable + a moving `vMAJOR`), not per-action subdir-prefixed tags. Consumers still SHA-pin; the tag exists so a pinned SHA maps to a version for Dependabot and the `hht_admin` cross-repo pin-drift check (CUR-1422). A release bumps the version label for the whole library even if one action changed — acceptable because consumers pin SHAs, and per-action tags aren't recognized by Dependabot for subdir-action pins.
- **Markdown line-art / diagrams**: ASCII only, fenced with ```text (per `~/.claude/CLAUDE.md` global rule and `.markdownlint.json` permissiveness around line length / HTML).
- **Branch protection is Terraform-owned**: `main` protection is a `github_repository_ruleset` resource for this repo in `cure-hht/hht_admin/terraform/branch-protection.tf`. `docs/branch-protection.md` describes what that ruleset requires; adding a new required check is a two-repo change — add the job (and its bare check-run name) here, then add that name to this repo's `github_repository_ruleset` in `hht_admin`.

## Where to look for context

- `README.md` — consumer-facing usage; canonical glossary in the **Reference** section (ADC, WIF, attribute condition, principalSet, etc.). Use it when terms in action READMEs need disambiguation.
- `docs/branch-protection.md` — the required-check set enforced on `main` and how the bare check-run names are chosen; protection is owned by a `github_repository_ruleset` in `hht_admin/terraform/branch-protection.tf`, not applied from here.
- Each action's `README.md` — declares its `Why this exists` line that references the spec ID in `cure-hht/hht_admin/spec/ops-secrets-architecture.md` (e.g. `HHT-OPS-identity-over-keys/A`). When changing an action's contract, check whether the spec ID still describes it.
- `hooks/` — Cure-HHT-specific pre-commit hooks shared to consumer repos (via the `.pre-commit-hooks.yaml` manifest): `release-notes-update/`, `no-or-true-guard/`, and `confidential-terms-scan/`. Hooks that aren't appropriate for a public hooks repo live here.
