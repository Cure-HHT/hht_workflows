# hht_workflows

Shared GitHub Actions composite actions for the Cure-HHT organization.
This repo is **public** so that public consumer repos (e.g.
[`cure-hht/event_sourcing`](https://github.com/Cure-HHT/event_sourcing))
can `uses:` actions from here. Confidential infrastructure (Terraform,
secrets, customer-identifying configuration) lives in
[`cure-hht/hht_admin`](https://github.com/Cure-HHT/hht_admin), which
stays private.

## Start here

New to this repo? After cloning, run once (idempotent):

```sh
scripts/setup.sh          # activate this clone's git hooks
scripts/setup.sh --check  # verify the clone is set up (reports via exit status)
scripts/test.sh           # run the test suite (scripts/test.sh --list to resolve targets)
```

`scripts/setup.sh` sets `core.hooksPath` and caches the pre-commit
environments; nothing else is required to start contributing. For how this
repo fits the wider organization, see
[The estate at a glance](#the-estate-at-a-glance).

Every Cure-HHT repo owes a fresh clone this same three-command path — the
contract is `HHT-OPS-repo-bootstrap` in `hht_admin/spec/`, and this repo hosts
its reusable enforcement (see
[Fresh-clone conformance](#fresh-clone-conformance-repo-bootstrap)).

## The estate at a glance

The canonical, org-wide map of the Cure-HHT repositories: what each holds, its
visibility, and how they relate. Every covered repo's README links up here, so
this is the one place the picture is maintained.

```text
                         Cure-HHT GitHub organization
  +-------------------------------------------------------------------------+
  |                                                                         |
  |   hht_admin (PRIVATE)                hht_workflows (PUBLIC)              |
  |   org IaC, WIF/OIDC pool,            reusable composite actions,        |
  |   ops-bot App, sponsor               org-required checks, the           |
  |   scaffolding, authoritative spec/   reusable repo-bootstrap workflow   |
  |        |                                   ^                            |
  |        | scaffolds                         | consumes (SHA-pinned)      |
  |        v                                   |                            |
  |   hht_sponsor_iac (PRIVATE)         hht_diary (PRIVATE today)           |
  |   sponsor-neutral IaC modules,      core app, shared packages,         |
  |   CD templates, onboarding scaffold  mobile app, public CI spec         |
  |        |                                   |                            |
  |        | copied + re-namespaced            | overlaid by               |
  |        v                                   v                            |
  |   hht_diary_<sponsor> (PRIVATE) -- per-sponsor build: config, branding,  |
  |                                    specs, IaC; deploys to its own GCP    |
  |                                                                         |
  |   Public libraries: event_sourcing, dart_opentimestamps                 |
  |   Publish target:   testlab-dashboard (PRIVATE)                         |
  +-------------------------------------------------------------------------+
```

| Repo | Visibility | Holds |
| --- | --- | --- |
| [`hht_admin`](https://github.com/Cure-HHT/hht_admin) | private | Org IaC (Terraform, WIF/OIDC pool, the ops-bot GitHub App), sponsor scaffolding, and the **authoritative** `spec/` of `HHT-OPS-*` requirements. |
| `hht_workflows` (this repo) | public | Reusable composite actions, the org-required CI checks, and the reusable repo-bootstrap workflow. |
| [`hht_sponsor_iac`](https://github.com/Cure-HHT/hht_sponsor_iac) | private | Sponsor-neutral Terraform modules, continuous-delivery templates, and the new-sponsor onboarding scaffold. |
| [`hht_diary`](https://github.com/Cure-HHT/hht_diary) | private (today) | Core application, shared packages, the mobile app, and the public CI spec. Slated to split into a generic core + instantiation before going public. |
| `hht_diary_<sponsor>` | private | A single sponsor's build: config, branding, specs, and IaC; deploys to that sponsor's own GCP project. |
| [`event_sourcing`](https://github.com/Cure-HHT/event_sourcing) | public | Event-sourcing library (Dart). |
| [`dart_opentimestamps`](https://github.com/Cure-HHT/dart_opentimestamps) | public | OpenTimestamps library (Dart). |
| [`testlab-dashboard`](https://github.com/Cure-HHT/testlab-dashboard) | private | Firebase Test Lab dashboard data, written by CI via a scoped App token. |

The public/secret boundary: confidential infrastructure — Terraform, secrets,
and any customer-identifying configuration — lives only in the private repos.
The public repos (this one, `event_sourcing`, `dart_opentimestamps`) carry no
sponsor identity; a sponsor name is data derived at runtime, never key material.

## What's here

Three composite actions implementing the org-level branch-protection
ruleset's required status checks:

| Action | Check name |
| --- | --- |
| [`validate-pr-title`](.github/actions/validate-pr-title/) | `Validate PR Title` |
| [`secrets-scan`](.github/actions/secrets-scan/) | `Security - Check for Secrets` |
| [`validation-summary`](.github/actions/validation-summary/) | `Validation Summary` |

Each of these is paired with a thin wrapper workflow that dogfoods it
on this repo's own PRs.

Plus consumer-invoked actions (not required checks, no wrapper here — see
each action's README for usage):

| Action | Purpose |
| --- | --- |
| [`slack-notify`](.github/actions/slack-notify/) | Resolves channel routing from caller's `slack-channels.yml` and posts via Slack `chat.postMessage`; optionally DMs a user resolved by email (`dm-user-email`) |
| [`email-notify`](.github/actions/email-notify/) | Send an email via the Gmail API as the org sending identity using WIF + domain-wide delegation — no static keys, no SMTP |
| [`previous-run-conclusion`](.github/actions/previous-run-conclusion/) | Report the previous completed run's conclusion for the current workflow/branch, so pager workflows can post green "recovered" messages after red runs |
| [`release-notes-publish`](.github/actions/release-notes-publish/) | Slice the current version's section from `RELEASE_NOTES.md` + pending fragments and emit as step outputs for downstream Slack/release tooling |
| [`confidential-terms-scan`](.github/actions/confidential-terms-scan/) | Four-surface confidential-terms scan (content, names, paths, PR metadata); prohibit list fetched at scan time from the consumer's scan-* Doppler project |
| [`firebase-test-lab-android`](.github/actions/firebase-test-lab-android/) | Run an Android instrumentation matrix on Firebase Test Lab; capture evidence + catalog, expose the matrix exit code as an output |
| [`firebase-test-lab-ios`](.github/actions/firebase-test-lab-ios/) | Run an iOS XCTest matrix on Firebase Test Lab with catalog-aware device fallback and exit-15 retries; expose the matrix exit code as an output |
| [`testlab-dashboard-publish`](.github/actions/testlab-dashboard-publish/) | Recover Test Lab run IDs from evidence, fetch Tool Results, and commit `dashboard_data.json` to the dashboard repo via a per-job App token |
| [`sponsor-base-preflight`](.github/actions/sponsor-base-preflight/) | Reject a sponsor build whose core base images are not digest-pinned, or whose pinned `portal-server` does not declare every permission the sponsor's `role-permissions.yaml` grants |

## Pre-commit hooks shared from this repo

In addition to the actions above, this repo exposes pre-commit hooks for
consumer repos to install via `repo: https://github.com/Cure-HHT/hht_workflows`
in their `.pre-commit-config.yaml`:

| Hook | Purpose |
| --- | --- |
| [`release-notes-update`](hooks/release-notes-update/) | Maintain per-PR release-notes fragments and consolidate them into a versioned `RELEASE_NOTES.md` |
| [`no-or-true-guard`](hooks/no-or-true-guard/) | Block the `\|\| true` / `\|\| :` shell short-circuit fallback in shell/YAML/Dockerfile/Makefile content |
| [`confidential-terms-scan`](hooks/confidential-terms-scan/) | Pre-push scan of added content, file/dir names, and branch name for confidential terms fetched at scan time from the consumer's `scan-*` Doppler project |

## Consuming from another Cure-HHT repo

Add these three workflow files to the consumer repo's
`.github/workflows/`:

### `validate-pr-title.yml`

```yaml
name: Validate PR Title
on:
  pull_request:
    types: [opened, synchronize, reopened, edited]
permissions:
  contents: read
jobs:
  validate:
    name: Validate PR Title
    runs-on: ubuntu-latest
    timeout-minutes: 2
    steps:
      - uses: Cure-HHT/hht_workflows/.github/actions/validate-pr-title@<commit-sha>  # SHA-pin; see "Pinning & versioning"
```

### `secrets-scan.yml`

```yaml
name: Security - Check for Secrets
on:
  pull_request:
    types: [opened, synchronize, reopened]
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  scan:
    name: Security - Check for Secrets
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # gitleaks needs full history
      - uses: Cure-HHT/hht_workflows/.github/actions/secrets-scan@<commit-sha>  # SHA-pin; see "Pinning & versioning"
```

### `validation-summary.yml`

```yaml
name: Validation Summary
on:
  pull_request:
    branches: [main]
    types: [opened, synchronize, reopened, edited]
permissions:
  checks: read
  statuses: read
  actions: read
  pull-requests: write
jobs:
  gate:
    name: Validation Summary
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: Cure-HHT/hht_workflows/.github/actions/validation-summary@<commit-sha>  # SHA-pin; see "Pinning & versioning"
```

The job's `name:` field becomes the check-context name that the
org-level ruleset matches against. Each consumer's wrappers must use
these exact names.

## Fresh-clone conformance (repo-bootstrap)

Every covered repo owes a fresh clone a documented path from "just cloned" to
"enforcement active, tests runnable" — the contract is `HHT-OPS-repo-bootstrap`
(A–H) in `hht_admin/spec/`. This repo hosts its shared enforcement:

- [`.github/workflows/repo-bootstrap.yml`](.github/workflows/repo-bootstrap.yml)
  — a reusable `workflow_call` that, on a real fresh checkout, asserts the clone
  starts with hooks inert, runs the repo's own `setup`/`verify`/`test` commands,
  and confirms the entry document names all three. It is language-agnostic: the
  four semantic inputs say *what* each command must achieve, not how.
- [`bootstrap/hooks-guard.sh`](bootstrap/hooks-guard.sh) — the one guard
  implementation each repo vendors and invokes from a developer entry point, so
  an inert clone says so (`/F`). It exposes a CI-silent warning
  (`hht_hooks_guard`) and a pure predicate (`hht_hooks_active`) for an
  authoritative verify command; both resolve an absolute `core.hooksPath`
  before comparing.

A consumer wires the depth check by adding `.github/workflows/repo-bootstrap-check.yml`:

```yaml
name: Repo Bootstrap
on:
  pull_request:
  schedule:
    - cron: '0 6 * * 1'
  workflow_dispatch:
permissions:
  contents: read
jobs:
  bootstrap:
    name: Repo Bootstrap
    uses: Cure-HHT/hht_workflows/.github/workflows/repo-bootstrap.yml@<commit-sha>  # SHA-pin; see "Pinning & versioning"
    with:
      setup-cmd: scripts/setup.sh
      check-cmd: scripts/setup.sh --check
      test-cmd: scripts/test.sh
      test-list-cmd: scripts/test.sh --list   # cheap "resolve targets" invocation
      guard-cmd: scripts/test.sh --list       # must name the setup command with hooks inert
      entry-doc: README.md
      runtime: python                         # 'python' | 'dart' | 'none'
```

Do **not** paths-filter this workflow: it becomes a required check, and a
paths-filtered required check wedges any PR that does not touch a matching file
at "Expected" forever. The check is cheap (shallow checkout, no full suite).

## Pinning & versioning

Consumers **SHA-pin** every `uses:` reference to this repo
(`Cure-HHT/hht_workflows/.github/actions/<name>@<40-char-sha>`), per
`HHT-OPS-composite-action-library/B` in `hht_admin`. Do **not** pin to
`@main` or a moving tag — an unreviewed change here would otherwise reach
every consumer on their next run.

### Versioning & releases

This repo follows semantic versioning:

- **`vMAJOR.MINOR.PATCH`** (immutable, e.g. `v1.0.0`) is cut for each set
  of changes consumers may adopt. A MAJOR bump signals a breaking change
  to an action's input/output contract (`HHT-OPS-composite-action-library/F`);
  MINOR/PATCH are backward-compatible.
- **`vMAJOR`** (e.g. `v1`) is a moving tag re-pointed to the latest release
  within that major. It exists only for **discoverability and SHA→version
  mapping** (Dependabot, the drift check, humans reading releases) — consumers
  SHALL NOT reference it in `uses:`; they always SHA-pin, as above.

Each release tag points at a `main` commit. Because consumers SHA-pin, the
tag is what maps a pinned SHA to a version: Dependabot (`github-actions`
ecosystem, enabled in this repo and every consumer) opens a **reviewed** PR
when a newer release exists, and the cross-repo pin-drift check in `hht_admin`
flags consumers that pin an untagged SHA or that disagree across
`hht_diary` ↔ `hht_diary_<sponsor>`. No auto-update — bumps are explicit and
reviewed.

**Cutting a release:** merge to `main`, then
`gh release create vX.Y.Z --target <main-sha>`, and re-point the major tag:
`git tag -f vMAJOR <sha> && git push -f origin vMAJOR`.

## Local hooks (pre-commit framework)

This repo and its consumers standardize on the
[pre-commit framework](https://pre-commit.com) for local git hooks.
Hook configuration is in `.pre-commit-config.yaml`; thin wrappers in
`.githooks/` invoke the framework via `core.hooksPath`. Cure-HHT-specific
hooks live in `hooks/` (`release-notes-update`, `no-or-true-guard`,
`confidential-terms-scan`) and are shared to consumer repos via the
`.pre-commit-hooks.yaml` manifest at the repo root.

### Setup

After cloning, run once per clone:

```sh
scripts/setup.sh
```

This sets `core.hooksPath = .githooks` (shared across all worktrees of
the clone) and pre-populates the hook environments. It requires
`pre-commit` on PATH; if absent, the script prints install instructions
and exits.

### What runs

- `pre-commit/pre-commit-hooks` — trailing-whitespace, end-of-file-fixer, check-merge-conflict, check-yaml, check-added-large-files
- `gitleaks/gitleaks` — secret scanning at pre-commit and pre-push (mirrors the org-required CI Security check)
- `igorshubovych/markdownlint-cli` — markdown linting
- `rhysd/actionlint` — GitHub Actions YAML validation
- `no-or-true-guard` — blocks the `|| true` / `|| :` shell short-circuit fallback
- `confidential-terms-scan` — pre-push confidential-terms scan (dogfoods the shared hook)

### Manual run

```sh
pre-commit run --all-files       # everything
pre-commit run gitleaks          # one hook
```

### Bypass (NOT recommended)

```sh
git commit --no-verify
```

## Related Repos

See [The estate at a glance](#the-estate-at-a-glance) for the full org-wide map
of repositories, their visibility, and how they relate.

### Current consumers

| Repo | Visibility | Wired up |
| --- | --- | --- |
| [`hht_admin`](https://github.com/Cure-HHT/hht_admin) | private | 2026-05-09 (CUR-1317) |
| [`event_sourcing`](https://github.com/Cure-HHT/event_sourcing) | public | 2026-05-09 (CUR-1317) |

## Reference

Brief definitions for the jargon that pops up in this repo. Each entry
links to an authoritative third-party source for depth.

| Term | One-liner | More |
| --- | --- | --- |
| **ADC** (Application Default Credentials) | GCP's discovery mechanism that lets libraries find credentials via env vars / files — what `google-github-actions/auth` sets up. | [GCP docs](https://cloud.google.com/docs/authentication/application-default-credentials) |
| **attribute condition** (WIF) | A boolean expression on an OIDC token's claims that gates which workflow tokens a WIF provider will accept (e.g. `attribute.repository == "Cure-HHT/hht_workflows"`). | [GCP docs](https://cloud.google.com/iam/docs/workload-identity-federation#conditions) |
| **branch protection** | GitHub feature that constrains pushes/merges to a branch via required reviews, required status checks, and similar rules. | [GitHub docs](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) |
| **CODEOWNERS** | File at `.github/CODEOWNERS` declaring which team/user must review changes to specific paths. | [GitHub docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners) |
| **composite action** | A GitHub Action assembled from multiple `runs.steps`, invokable from a workflow via `uses:`. This repo is entirely composite actions. | [GitHub docs](https://docs.github.com/en/actions/sharing-automations/creating-actions/creating-a-composite-action) |
| **Doppler** | Secret-manager SaaS. The Cure-HHT source of truth for runtime secrets; CI fetches at job time via OIDC, never via static tokens. | [Doppler docs](https://docs.doppler.com/docs/about) |
| **gitleaks** | Open-source scanner that detects committed secrets via regex patterns. Used by the `secrets-scan` action. | [gitleaks](https://github.com/gitleaks/gitleaks) |
| **IAM** (Identity & Access Management) | GCP's permission model: a member (user, SA, or principalSet) holds a role on a resource. | [GCP docs](https://cloud.google.com/iam/docs/overview) |
| **OIDC** (OpenID Connect) | Identity protocol layered on OAuth 2.0; how a workflow proves to a third party "I'm GitHub Actions running in repo X". | [GitHub OIDC docs](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect) |
| **principalSet** (GCP) | IAM identifier representing a *set* of identities (e.g. all workflow runs from one repo) that can impersonate a service account via WIF. | [GCP docs](https://cloud.google.com/iam/docs/principal-identifiers#principal-sets) |
| **service account** (GCP) | A non-human identity that workloads use to call GCP APIs. WIF lets GitHub workflows impersonate one without long-lived keys. | [GCP docs](https://cloud.google.com/iam/docs/service-account-overview) |
| **SHA pinning** | Referencing a GitHub Action by its commit SHA (not branch or tag). The org-recommended posture for third-party actions. | [GitHub hardening guide](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions#using-third-party-actions) |
| **status check** | A pass/fail result a CI job reports back to GitHub; branch protection can require named checks to pass before merge. | [GitHub docs](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/about-status-checks) |
| **WIF** (Workload Identity Federation) | GCP mechanism that lets external identities (GitHub Actions, AWS, etc.) impersonate GCP service accounts via short-lived tokens — no JSON keys. | [GCP docs](https://cloud.google.com/iam/docs/workload-identity-federation) |

## License

AGPLv3 — see [LICENSE](LICENSE).
