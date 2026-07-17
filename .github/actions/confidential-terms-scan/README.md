# confidential-terms-scan (composite action)

**Why this exists:** `HHT-OPS-confidential-keywords-scrubbing/C,D` — the PR-CI
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
- The fetched list exists only as a masked env var for the scan step.
