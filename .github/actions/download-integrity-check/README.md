# download-integrity-check

Runs the [`download-integrity`](../../../hooks/download-integrity/) pre-commit
hook over the whole repository in CI.

**Why this exists:** `HHT-OPS-ci-tool-download-integrity/C`. A local hook can be
bypassed; this check cannot. The consumer repository must configure the
`download-integrity` hook in its own `.pre-commit-config.yaml` (see the hook's
README).

## Usage

    - uses: actions/checkout@<sha>
    - uses: Cure-HHT/hht_workflows/.github/actions/download-integrity-check@<sha>
