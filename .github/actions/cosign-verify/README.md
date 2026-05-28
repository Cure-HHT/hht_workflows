# cosign-verify

Verifies keyless cosign signatures on fully-pinned container image digests.

## Usage

    - uses: Cure-HHT/hht_workflows/.github/actions/cosign-verify@<sha>
      with:
        images: |
          ghcr.io/cure-hht/portal-final@sha256:...
          ghcr.io/cure-hht/diary-final@sha256:...
        soft-fail: 'true'   # 'false' to block the job on failure

## What it does

Wraps `sigstore/cosign-installer` (SHA-pinned internally; version override via
`cosign-version` input) and performs keyless signature verification using the
Cure-HHT standard certificate-identity-regexp and OIDC issuer. Implements a
retry/backoff loop (the Sigstore verify side can flake) and an optional
soft-fail mode that mirrors the SBOM-attestation pattern.

**Default behavior:**
- Verifies 1 or more fully-pinned images (digest form, not tags).
- Uses 5 retry attempts with exponential backoff (attempt * 15 seconds).
- On persistent failure, logs a `::warning::` and exits 0 (soft-fail mode).

**Security-gate vs advisory mode:**
Set `soft-fail: 'false'` when this step is a required security gate (the job
must fail if verification fails). The `'true'` default mirrors the
SBOM-attestation pattern — advisory, non-blocking — and is appropriate when
Sigstore flakes should not fail your pipeline.

**Pinning:**
Always pin this action by SHA in your workflows. Tags and branches are
explicitly discouraged — they can change without your knowledge.

    # Bad: do not use
    - uses: Cure-HHT/hht_workflows/.github/actions/cosign-verify@main
    - uses: Cure-HHT/hht_workflows/.github/actions/cosign-verify@v1.0.0

    # Good: pin by full commit SHA
    - uses: Cure-HHT/hht_workflows/.github/actions/cosign-verify@abc123def456...

## Inputs

| Input | Description | Default | Required |
|-------|-------------|---------|----------|
| `images` | Newline-separated list of fully-pinned image refs (name@sha256:...). Tags are NOT accepted. | — | Yes |
| `identity-regexp` | cosign `--certificate-identity-regexp` value. | `https://github.com/${{ github.repository }}` | No |
| `oidc-issuer` | cosign `--certificate-oidc-issuer` value. | `https://token.actions.githubusercontent.com` | No |
| `retries` | Max verification attempts per image. | `5` | No |
| `soft-fail` | `'true'`: log warning and exit 0 on failure. `'false'`: exit 1 and fail the job. | `'true'` | No |
| `cosign-version` | Override the cosign-installer release (e.g. `'v2.4.1'`). Defaults to the SHA-pinned v3.x. | `''` | No |

## Why this exists

Consolidates three near-duplicate inline cosign-verify implementations across
the org (existing in `hht_diary/build-ghcr-containers.yml`, planned for
callisto builds, future sponsor-build-template workflows). Centralizes the
upstream `cosign-installer` version and enforces retry/soft-fail consistency.

Implements `CAL-OPS-deploy-provenance-traceability` from
`Cure-HHT/hht_diary_callisto/spec/ops-deployment.md`.
