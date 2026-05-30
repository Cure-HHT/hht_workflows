# doppler-cli-oidc-auth

Mints a CLI-usable Doppler token for a job via GitHub OIDC; exposes it as
a masked `DOPPLER_TOKEN` environment variable. Callers then invoke the
`doppler` CLI normally (`doppler configs ...`, `doppler secrets ...`)
using the identity's permissions.

Distinct from [`doppler-oidc-auth`](../doppler-oidc-auth/README.md), which
fetches secrets from a SINGLE config and injects them as env vars. Use
this action when the job needs CLI access across multiple configs or
projects (audit / manifest / enumeration use cases).

## Usage

    jobs:
      manifest:
        runs-on: ubuntu-latest
        permissions:
          id-token: write   # required for the OIDC exchange
          contents: read
        steps:
          - uses: actions/checkout@v4

          - uses: Cure-HHT/hht_workflows/.github/actions/doppler-cli-oidc-auth@<sha>
            with:
              doppler_identity_id: ${{ vars.ADMIN_AUDIT_DOPPLER_IDENTITY_ID }}

          - name: Enumerate Doppler configs
            run: doppler configs --project admin --json

## Required workflow permissions

    permissions:
      id-token: write   # MUST be at job or workflow scope
      contents: read

## What it does

1. Requests a GitHub OIDC token bound to the calling job
   (audience `https://github.com/Cure-HHT`).
2. Exchanges it at Doppler's `/v3/auth/oidc` endpoint for a short-lived
   Doppler access token scoped to whatever the identity has permission
   to read.
3. Masks the token via `::add-mask::` BEFORE exporting it -- without that
   ordering, the token would appear unmasked in subsequent log lines.
4. Exports `DOPPLER_TOKEN` to `$GITHUB_ENV` for downstream steps.
5. Self-checks by hitting `/v3/projects?per_page=1` to confirm the token
   works.

There is no `inject-env-vars` mode on this action; that pattern belongs
to `doppler-oidc-auth`. There is no `project` or `config` input; the
identity's own permissions determine read scope.

Sibling action `doppler-oidc-auth` pins
`dopplerhq/secrets-fetch-action@451892f16195f9ac360e1a5bcbf0b5fd0e957534`
(v2.0.0). This action does not depend on the upstream Doppler action --
the OIDC exchange is implemented inline via `curl` against
`POST https://api.doppler.com/v3/auth/oidc` so we control the masking
ordering directly.

## Why this exists

Implements `HHT-OPS-identity-over-keys/B` and
`HHT-OPS-composite-action-library/A,B,F` from
`Cure-HHT/hht_admin/spec/ops-secrets-architecture.md`. The OIDC handshake
is implemented once here and consumed by reference; consumer repos SHA-pin
this action; upgrades happen in one place.

## Breaks if

- Workflow lacks `permissions: id-token: write`.
- The identity UUID (`doppler_identity_id`) does not exist in the Doppler
  dashboard.
- The identity is not configured to accept the calling
  `job_workflow_ref:` as an OIDC source.
- The identity has no project permissions (the self-check `/v3/projects`
  call returns 0 results and the response parsing fails).
