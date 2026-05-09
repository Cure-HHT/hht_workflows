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

Plus one notification action consumed *inside* deploy/build workflows
(not a required check, no wrapper here — see its README for usage):

| Action | Purpose |
| --- | --- |
| [`slack-notify`](.github/actions/slack-notify/) | Resolves channel routing from caller's `slack-channels.yml` and posts via Slack `chat.postMessage` |

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

## License

AGPLv3 — see [LICENSE](LICENSE).
