# hht_workflows

Shared GitHub Actions composite actions for the Cure-HHT organization.
This repo is **public** so that public consumer repos (e.g.
[`cure-hht/event_sourcing`](https://github.com/Cure-HHT/event_sourcing))
can `uses:` actions from here. Confidential infrastructure (Terraform,
secrets, customer-identifying configuration) lives in
[`cure-hht/hht_admin`](https://github.com/Cure-HHT/hht_admin), which
stays private.

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
| [`slack-notify`](.github/actions/slack-notify/) | Resolves channel routing from caller's `slack-channels.yml` and posts via Slack `chat.postMessage` |
| [`release-notes-publish`](.github/actions/release-notes-publish/) | Slice the current version's section from `RELEASE_NOTES.md` + pending fragments and emit as step outputs for downstream Slack/release tooling |

## Pre-commit hooks shared from this repo

In addition to the actions above, this repo exposes pre-commit hooks for
consumer repos to install via `repo: https://github.com/Cure-HHT/hht_workflows`
in their `.pre-commit-config.yaml`:

| Hook | Purpose |
| --- | --- |
| [`release-notes-update`](hooks/release-notes-update/) | Maintain per-PR release-notes fragments and consolidate them into a versioned `RELEASE_NOTES.md` |

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
      - uses: Cure-HHT/hht_workflows/.github/actions/validate-pr-title@main
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
      - uses: Cure-HHT/hht_workflows/.github/actions/secrets-scan@main
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
      - uses: Cure-HHT/hht_workflows/.github/actions/validation-summary@main
```

The job's `name:` field becomes the check-context name that the
org-level ruleset matches against. Each consumer's wrappers must use
these exact names.

## Pinning

Pin to `@main` for auto-update (a fix in this repo lands in all
consumers on their next workflow run). Pin to `@<commit-sha>` or
`@<tag>` if you need stability against unintended changes here.

## Local hooks (pre-commit framework)

This repo and its consumers standardize on the
[pre-commit framework](https://pre-commit.com) for local git hooks.
Hook configuration is in `.pre-commit-config.yaml`; thin wrappers in
`.githooks/` invoke the framework via `core.hooksPath`. Cure-HHT-specific
hooks that aren't appropriate for a public hooks repo live in `hooks/`
(currently empty; will be populated as cross-cutting needs emerge).

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
- `gitleaks/gitleaks` — secret scanning (mirrors the org-required CI Security check)
- `igorshubovych/markdownlint-cli` — markdown linting
- `rhysd/actionlint` — GitHub Actions YAML validation

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

| Repo | What it holds |
| --- | --- |
| `hht_workflows` (this repo, public) | Shared GitHub Actions composite actions; required-check workflows |
| [`hht_admin`](https://github.com/Cure-HHT/hht_admin) (private) | Org-wide GCP infrastructure (Terraform, IAM, service accounts); customer-identifying configuration |

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
