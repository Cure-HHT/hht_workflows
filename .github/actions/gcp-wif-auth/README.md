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

Wraps `google-github-actions/auth@v2` pinned to a specific SHA, with the
Cure-HHT defaults: `create_credentials_file: true`,
`export_environment_variables: true`. After this action runs, subsequent
steps can invoke `gcloud`, `gsutil`, or any Google client library without
further auth.

## Why this exists

Implements `HHT-OPS-identity-over-keys/A` from
`Cure-HHT/hht_admin/spec/ops-secrets-architecture.md`. Centralizes the
upstream SHA so upgrades happen in one place; enforces the audience and
attribute-condition standards by construction.
