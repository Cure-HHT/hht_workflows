# doppler-oidc-auth

Fetches Doppler secrets for a job via OIDC; injects all secrets in the
(project, config) as masked environment variables on the job.

## Usage

    jobs:
      deploy:
        runs-on: ubuntu-latest
        permissions:
          id-token: write   # required by the Doppler OIDC exchange
          contents: read
        steps:
          - uses: actions/checkout@v4

          - uses: Cure-HHT/hht_workflows/.github/actions/doppler-oidc-auth@<sha>
            with:
              doppler_identity_id: ${{ vars.READINESS_DOPPLER_IDENTITY_ID }}
              doppler_project: ${{ vars.READINESS_DOPPLER_PROJECT }}
              doppler_config: ${{ vars.READINESS_DOPPLER_CONFIG }}

          - name: Use a fetched secret
            run: |
              # All secrets in the (project, config) are now masked env vars.
              echo "DB_HOST is set: ${DB_HOST:+yes}"
              ./deploy.sh

## Required workflow permissions

    permissions:
      id-token: write   # MUST be at job or workflow scope
      contents: read

## What it does

Wraps `dopplerhq/secrets-fetch-action@v2.0.0` (SHA
`451892f16195f9ac360e1a5bcbf0b5fd0e957534`) with `inject-env-vars: true`
hardcoded and `auth-method: oidc` hardcoded. The OIDC identity exchange
happens internally inside the upstream action: it requests a GitHub OIDC
token, presents it to the Doppler identity endpoint, and receives a
short-lived scoped token. All secrets in the (project, config) land as
masked environment variables on the job after this action completes.

There is no `inject_env_vars` input on this wrapper — the opinionated
contract is "secrets become masked env vars". Callers that need the
outputs-mode pattern (e.g. reading individual secret values into step
outputs) can use `dopplerhq/secrets-fetch-action` directly.

The composite scope IS the (project, config) pair. The upstream action
fetches all secrets in that config; there is no per-secret allowlist input
on this wrapper. Choose a tightly scoped config to limit exposure.

## Why this exists

Implements `HHT-OPS-identity-over-keys/B` and
`HHT-OPS-one-source-of-truth-per-secret-value/A,B` from
`Cure-HHT/hht_admin/spec/ops-secrets-architecture.md`. No static
`DOPPLER_TOKEN` is stored anywhere; the ephemeral identity token is minted
per job and expires with it.

Implements `HHT-OPS-composite-action-library/A,B,F` from the same spec:
the OIDC handshake is implemented once here and consumed by reference;
upgrades happen in one place; the input contract is declared with
`description:` and `required:` fields.

## Breaks if

- Workflow lacks `permissions: id-token: write`.
- The identity UUID (`doppler_identity_id`) does not exist in the Doppler
  dashboard, or the identity is not configured to accept the calling
  repository as an OIDC source.
- The identity does not have access to the requested project / config.
- The `doppler_project` or `doppler_config` slug is mistyped.
