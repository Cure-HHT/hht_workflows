# confidential-terms-scan (composite action)

**Why this exists:** `HHT-OPS-confidential-keywords-scrubbing/B,C,F,G,I` — the PR-CI
enforcement point of the confidential-terms guard. The same engine backs the
`confidential-terms-scan` pre-push hook (`hooks/confidential-terms-scan/`),
whose README carries the full runbook and triage doctrine.

## Usage (consumer PR CI)

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened, edited]  # 'edited' re-scans title/body

permissions:
  id-token: write   # Doppler OIDC
  contents: read

jobs:
  confidential-terms-scan:      # run in a dedicated job (see Contract below)
    runs-on: ubuntu-latest
    permissions:
      id-token: write   # Doppler OIDC
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0          # the scan diffs base..head
      - uses: Cure-HHT/hht_workflows/.github/actions/confidential-terms-scan@<sha>
        with:
          doppler_identity_id: ${{ vars.CONFIDENTIAL_SCAN_DOPPLER_IDENTITY_ID }}
          doppler_project: scan-<consumer>
```

## Contract

- Inputs: see `action.yml`. `test_terms` is internal to `hht_workflows`
  readiness tests; consumers must never set it.
- Output: pass/fail only. Failure output carries counts, `file:line`
  locations, masked paths, and metadata field names — never matched text.
- The fetch step injects `CONFIDENTIAL_PROHIBIT_LIST` via `GITHUB_ENV`
  (`inject-env-vars: true`), so it persists as a plain env var for the
  remainder of the calling job, not just the scan step. Run this action in
  a dedicated job (as above) so the value's exposure ends when that job
  ends, rather than leaking into unrelated later steps of a shared job.
