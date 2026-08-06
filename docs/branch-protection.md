# Branch protection (hht_workflows)

The `main` branch of `Cure-HHT/hht_workflows` is protected by a
`github_repository_ruleset` resource for this repo, declared in
`cure-hht/hht_admin/terraform/branch-protection.tf`. Terraform is the single
owner: the required-check list, review requirements, and merge rules live in
that resource, are reviewed as code, and are applied by the `hht_admin`
`terraform.yml` pipeline. This document describes what that ruleset enforces
and how the required-check names are chosen; it is not applied from here.

## Required status checks

The ruleset requires every job in this repo's PR gates to pass before a merge
to `main`, referenced by the **bare check-run name** GitHub stores on the
commit. For a job with no `name:` override that is the **job id**; for a job
that sets `name:`, it is that display name. (The UI shows
`<workflow-name> / <job-name>` and may append `(<event>)`, but those are
display affordances — the stored name, and the ruleset matcher, use the bare
name only.)

From `readiness-checks.yml` — one entry per job:

- `doppler-oidc-auth` — Doppler OIDC handshake readiness (secrets-injection variant)
- `doppler-cli-oidc-auth` — Doppler OIDC handshake readiness (CLI-token-mint variant)
- `gcp-wif-auth` — real WIF handshake readiness
- `release-notes-publish` — release-notes-publish composite action, end-to-end
- `cosign-verify` — cosign-verify composite action: keyless sign + verify happy path and a negative wrong-identity case
- `build-urs` — URS compile readiness (synthetic fixture to PDF + DOCX)
- `confidential-terms-scan` — scanner-action readiness: `test_terms` happy path plus the all-four-surfaces negative fixture (fixture-only; no Doppler identity)
- `confidential-terms-gate` — the real confidential-terms gate for this repo: scans the PR range against the live `scan-hht-workflows` Doppler prohibit list (assertion I)
- `notify-failure` — notify-failure composite action, end-to-end: unit tests, the jobs-API grant, and a real invocation whose Slack post soft-fails by design (fixture routing file, invalid token, nothing posted). Job id `notify-failure-readiness`; the bare id is reserved for the standard announcement job, so the job carries an explicit `name:` holding this context stable
- `notify-failure-lint` — notify-failure-lint composite action: unit tests plus the composite run against a conforming fixture (must pass) and one fixture directory per rejection rule (each must fail). Job id `notify-failure-lint-readiness`, `name:`-pinned for the same reason
- `sponsor-base-preflight` — sponsor-base-preflight composite action, end-to-end against a locally-seeded stand-in base image: the digest-pinned happy path plus two negatives, a mutable base tag and a grant the base does not declare (each must fail)

Two jobs in `readiness-checks.yml` are deliberately **not** required checks:

- the standard `notify-failure` announcement job (`name: Notify failure`) —
  its guard skips it on `pull_request` runs, so it has nothing to report on
  the event branch protection gates
- `no-op` — placeholder; retired as real jobs replace it

Both are named, with those reasons, in the parity lint described below, so a
job stops gating only by an edit someone reviewed.

From `release-notes-tests.yml`:

- `Release Notes Tests` — pytest suite for the hooks (`release-notes-update`, `no-or-true-guard`, `confidential-terms-scan`) and the publish action

`confidential-terms-gate` and `confidential-terms-scan` are distinct on
purpose: the fixture-only readiness job holds the bare id
`confidential-terms-scan`, so the real gate uses the id
`confidential-terms-gate` (no `name:` override) and that is the name the
ruleset requires. `cosign-verify` runs on every PR and is a required check
here too, so the one-entry-per-job invariant holds.

## Review requirements

The ruleset requires a pull request before merging and requires conversation
resolution. Code Owner review (`.github/CODEOWNERS`) and a minimum approval
count are enforced through the same resource; changing either is a change to
`branch-protection.tf`, reviewed like any other Terraform change.

## Why Terraform owns this

Branch protection for every Covered Repo — this one included — is declared as
`github_repository_ruleset` resources in `hht_admin/terraform`, so the
required-check set is version-controlled, reviewed, and applied uniformly
rather than hand-poked per repo. The org-wide ruleset stays separate: the
`confidential-terms-gate` and per-action readiness checks are repo-specific
and are required only through this repo's own `github_repository_ruleset`,
never added to the organization ruleset (repos that never report them would
otherwise wedge at "Expected" forever).

Adding a new required check here is therefore a two-repo change: add the job
(and its bare name) in this repo, and add that name to this repo's
`github_repository_ruleset` in `hht_admin/terraform/branch-protection.tf`.

Only the second half of that change is easy to forget, and what it costs is
narrower than it looks. A readiness job with no required context still blocks
a merge when it fails, because the org-wide `Validation Summary` check
aggregates every check run on the head commit. What the named context adds is
protection against the job going *absent*: the aggregate counts every
non-failure conclusion, `skipped` included, as passing, so a job that is
deleted, renamed, skipped by a guard, or cut off by a narrowed trigger leaves
nothing to notice. A required context sits at "Expected" and blocks.

`hht_admin` reconciles the two sides in its static checks
(`tools/gate_parity`): a readiness job with no required context fails the
lint, as does a required context that no job here reports, which would
otherwise wedge every PR on this repo at "Expected". A job that should not
gate is named there with its reason, so the list above and the ruleset cannot
drift apart unnoticed.
