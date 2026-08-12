# gcp-wif-auth

Authenticates a workflow job to GCP via Workload Identity Federation.

## Usage

    - uses: Cure-HHT/hht_workflows/.github/actions/gcp-wif-auth@<sha>
      with:
        workload_identity_provider: ${{ vars.WIF_PROVIDER }}
        service_account: ${{ vars.WIF_SA }}
        # Optional:
        # token_format: id_token     # default 'access_token'
        # audience: 'https://my-cloud-run.run.app'

## Required workflow permissions

    permissions:
      id-token: write    # MUST be at job or workflow scope
      contents: read

## What it does

Wraps `google-github-actions/auth@v3` pinned to a specific SHA, with the
Cure-HHT defaults: `create_credentials_file: true`,
`export_environment_variables: true`. After this action runs, the
runner has GCP Application Default Credentials (ADC) configured via
`GOOGLE_APPLICATION_CREDENTIALS` / `CLOUDSDK_*` env vars. Subsequent
steps that use ADC pick up the auth automatically.

This action does NOT install `gcloud` / `gsutil` / `bq`. The
`ubuntu-latest` runner happens to ship gcloud preinstalled, but
relying on that is fragile. If your job needs the CLI tools, add an
explicit setup step:

    - uses: google-github-actions/setup-gcloud@<sha>

Google client libraries (Python/Go/Node) and most third-party tooling
that reads ADC work without any further setup.

## Outputs

Consumers that need the raw token can read `steps.<id>.outputs.access_token`
(when `token_format: access_token`) or `steps.<id>.outputs.id_token`
(when `token_format: id_token`) — useful for cases where ADC isn't a fit
or for readiness-checking the WIF handshake without depending on a CLI
being installed.

## Why this exists

Implements `HHT-OPS-identity-over-keys/A` from
`Cure-HHT/hht_admin/spec/ops-secrets-architecture.md`. Centralizes the
upstream SHA so upgrades happen in one place; enforces the audience and
attribute-condition standards by construction.
