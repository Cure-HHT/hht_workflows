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
tools/setup-repo.sh          # activate this clone's git hooks
tools/setup-repo.sh --check  # verify the clone is set up (reports via exit status)
scripts/test.sh              # run the test suite (scripts/test.sh --list to resolve targets)
```

`tools/setup-repo.sh` sets `core.hooksPath` and caches the pre-commit
environments; nothing else is required to start contributing.

Every Cure-HHT repo owes a fresh clone this same three-command path — the
contract is `HHT-OPS-repo-bootstrap` in `hht_admin/spec/`, and this repo hosts
its reusable enforcement (see
[Fresh-clone conformance](#fresh-clone-conformance-repo-bootstrap)).

## Related repositories

The other Cure-HHT repositories this one works with, named so you know where to
look — they live under the same `Cure-HHT` GitHub organization:

- **`hht_admin`** (private) — org IaC (Terraform, WIF/OIDC pool, the ops-bot
  GitHub App), sponsor scaffolding, and the authoritative `spec/` of
  `HHT-OPS-*` requirements.
- **`hht_sponsor_iac`** (private) — sponsor-neutral Terraform modules, CD
  templates, and the new-sponsor onboarding scaffold.
- **`hht_diary`** (private today) — core application, shared packages, the
  mobile app, and the public CI spec.
- **`hht_diary_<sponsor>`** (private) — a single sponsor's build: config,
  branding, specs, and IaC.
- **`event_sourcing`**, **`dart_opentimestamps`** (public) — shared Dart
  libraries.
- **`testlab-dashboard`** (private) — Firebase Test Lab dashboard data.

Confidential infrastructure — Terraform, secrets, and any customer-identifying
configuration — lives only in the private repos. The public repos (this one,
`event_sourcing`, `dart_opentimestamps`) carry no sponsor identity.

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
| [`notify-failure`](.github/actions/notify-failure/) | The single way a workflow announces its own failure: derives the failed job/step from the run's own jobs API (no per-workflow config, no workflow-name list) and delegates the post to `slack-notify` |
| [`notify-failure-lint`](.github/actions/notify-failure-lint/) | Fails CI when a workflow triggered by push/schedule/workflow_dispatch lacks the standard `notify-failure` job, or announces failure off a hand-maintained `on.workflow_run.workflows` list |

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

### `notify-failure`

The single way a workflow announces its own failure. It derives which
job (and, where identifiable, which step) failed from the *current
run's own* GitHub Actions jobs API — no per-workflow configuration and
no workflow-name list to keep in sync — composes the Slack message, and
delegates delivery to `slack-notify`. If the announcement itself fails
to reach Slack, the step is soft-failed (the run stays green) but a
`::error::` annotation is emitted so the failure is visible on the run
without depending on Slack being up.

The caller **must**:

- run `actions/checkout` before the `notify-failure` step (so
  `slack-notify` can read the routing file from the caller's
  workspace), and
- grant `actions: read` (the jobs-API lookup 403s without it).

Inputs:

| Input | Required | Default | Purpose |
| --- | --- | --- | --- |
| `slack-token` | yes | — | Slack bot OAuth token (`xoxb-...`). |
| `event` | no | `workflow-failure` | Routing key looked up in the caller's `slack-channels.yml`. The default is a FLAT key (single channel), so a caller with no build flavor passes no `env`. |
| `env` | no | `""` | Routing sub-key. Pass ONLY when `event` names an env-keyed route — `slack-notify` errors by design on a flat/env-keyed mismatch. |
| `hints` | no | `""` | Optional JSON object string mapping a failed step's `name` (exactly as the jobs API reports it) to hint text, e.g. `'{"Upload to Google Play": "Play rejected the upload; check the track."}'`. Unmatched or absent produces no hint line; malformed JSON is warned about and ignored, never fatal. |
| `routing-file` | no | `.github/slack-channels.yml` | Path to the routing YAML, relative to the caller's workspace. |

Output: `post-status` — `ok` when the announcement reached at least
one channel, `soft-failed` otherwise.

This is the standard job. `notify-failure-lint` (below) checks for it
verbatim, so copy the `if:` guard exactly — it is not `failure()`:
`failure()` would also fire on a cancelled run, and the event test keeps
the announcement off pull-request runs, where the author is already
looking at the result.

```yaml
  notify-failure:
    name: Notify failure
    needs: [build, test]   # list every OTHER job in the workflow
    if: ${{ !cancelled() && contains(needs.*.result, 'failure') && github.event_name != 'pull_request' }}
    runs-on: ubuntu-latest
    permissions:
      contents: read
      actions: read
    steps:
      - uses: actions/checkout@v4
      - uses: Cure-HHT/hht_workflows/.github/actions/notify-failure@<commit-sha>  # SHA-pin; see "Pinning & versioning"
        with:
          slack-token: ${{ secrets.SLACK_BOT_TOKEN }}
```

### `notify-failure-lint`

The enforcement half of `notify-failure`: a static check that fails CI so
bespoke per-workflow notifiers cannot silently re-accrete. It reads the
consumer's workflow tree and applies two rules:

- **Presence.** A workflow is *covered* if its triggers include `push`,
  `schedule`, or `workflow_dispatch` (whatever else they include). Every
  covered workflow must carry the standard `notify-failure` job above —
  `needs:` naming every other job, the canonical `if:` guard,
  `contents: read` + `actions: read`, an `actions/checkout` step, and a
  SHA-pinned `notify-failure` reference. Workflows triggered only by
  `pull_request` / `workflow_call` are out of scope: PR failures already
  show as PR status checks, and a reusable workflow announces from its
  caller.
- **No workflow enumeration.** No workflow may key failure announcement off a
  hand-maintained list of other workflows. Two limbs: the `on:` block must not
  carry a `workflow_run.workflows` list, *and* a job containing a
  `slack-notify` step must not match `github.event.workflow_run.name` against
  a list read from a file or an input. Such a list holds workflow *display
  names*, matched exactly, with no wildcard support and no signal when an
  entry stops matching anything — which is exactly how the mechanism this
  action replaced rotted undetectably. Moving the list out of `on:` and into
  `watched-workflows.txt` changes nothing about that, so the second limb
  rejects it too. The second limb reads `run:` bodies and `if:` expressions
  alike, so `contains(fromJSON(vars.WATCHED), github.event.workflow_run.name)`
  on a `slack-notify` step is rejected as well. It is a narrow proxy that
  under-fires by design: the name must be an argument of a real *matching*
  command, so merely *mentioning* `workflow_run.name` in message text (or
  passing an unrelated `${{ inputs.channel }}` beside it) is fine, and a
  lookup split across two jobs by `needs:` is not detected.

There is no allowlist of workflow filenames in the checker: covered-ness
comes from each workflow's own triggers, so there is nothing to keep in
sync.

**Semantic exemption.** A workflow that announces failure with genuinely
custom semantics (say a maintenance report that posts its own summary) can
opt out of the presence rule with a real comment line anywhere in the file,
stating the outcome classification it publishes:

```yaml
# notify-failure: semantic-exempt - posts a monthly maintenance summary, failures included
```

Three things are required, none sufficient alone:

- The marker must be an actual top-level **comment line**, with `#` in
  **column 0**. The same text inside a `run:` string is not an exemption —
  neither quoted, nor as a shell comment inside a `run: |` block scalar.
- It must state a **classification** after a `-`, `:` or em-dash separator,
  with at least three consecutive letters in it (`- .` does not pass).
  A bare marker is rejected: the check enumerates accepted exemptions as
  `file -> classification` on its own log, which is the artifact a reviewer
  judges the carve-out by.
- The workflow must also contain a `slack-notify` step guarded by
  `failure()` or `always()`, so the marker cannot be pasted onto a workflow
  that in fact announces nothing.

The enumeration rule has no exemption.

Note that `permissions: read-all` on the notify job is **rejected**: the
check requires the canonical explicit form (`contents: read` plus
`actions: read`) so the grant is legible in the diff and cannot silently
widen. The lint also fails if `workflows-dir` names a directory containing
no `.yml`/`.yaml` files — a typo that checks nothing must not report
success.

The caller **must** run `actions/checkout` first — the lint reads the
workflow tree from the workspace.

| Input | Required | Default | Purpose |
| --- | --- | --- | --- |
| `workflows-dir` | no | `.github/workflows` | Directory of workflow YAML to check, relative to the workspace. |

```yaml
  notify-failure-lint:
    name: notify-failure lint
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5      # optional; see below
        with:
          python-version: '3.12'
      - uses: Cure-HHT/hht_workflows/.github/actions/notify-failure-lint@<commit-sha>  # SHA-pin; see "Pinning & versioning"
```

`actions/setup-python` is optional. The action needs PyYAML and prefers
whatever the runner already provides, installing it only when `import yaml`
fails — so it works on a bare runner and does not trip over a PEP 668
externally-managed interpreter. Adding `setup-python` pins the interpreter
and skips the install path entirely.

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

The required status-check context is **`Repo Bootstrap / Fresh clone`** — the
composition of the caller job's `name:` and the reusable job's `name:` (a
caller job that `uses:` a reusable workflow produces a check context of
`<caller job name> / <reusable job name>`). Every consumer must therefore name
its caller **workflow** `Repo Bootstrap` and its caller **job** `Repo
Bootstrap`, exactly as in the example below, and branch-protection rules must
require that exact composed string, `Repo Bootstrap / Fresh clone`.

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
      setup-cmd: tools/setup-repo.sh
      check-cmd: tools/setup-repo.sh --check
      test-cmd: scripts/test.sh
      test-list-cmd: scripts/test.sh --list   # cheap "resolve targets" invocation
      guard-cmd: scripts/test.sh --list       # must name the setup command with hooks inert
      entry-doc: README.md
      runtime: python                         # 'python' | 'dart' | 'none'
```

Do **not** paths-filter this workflow: it becomes a required check, and a
paths-filtered required check wedges any PR that does not touch a matching file
at "Expected" forever. The check is cheap (shallow checkout, no full suite).

### Cross-repo requirement citations

When a repo's `spec/` cites another Cure-HHT repo's requirements, those
citations resolve only if that repo is linked as an elspais **associate**.
Locally:

```sh
elspais associate --all     # links the sibling Cure-HHT repos you have cloned
elspais associate --list    # shows what resolved
```

`tools/setup-repo.sh` runs this for you; `tools/setup-repo.sh --check` reports it. In
CI the [`elspais-federate`](.github/actions/elspais-federate/) action does the
equivalent before `elspais checks`.

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
tools/setup-repo.sh
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

## Current consumers

Repos wired up to consume this repo's actions (see
[Related repositories](#related-repositories) for the wider set):

| Repo | Visibility | Wired up |
| --- | --- | --- |
| `hht_admin` | private | 2026-05-09 (CUR-1317) |
| `event_sourcing` | public | 2026-05-09 (CUR-1317) |

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
