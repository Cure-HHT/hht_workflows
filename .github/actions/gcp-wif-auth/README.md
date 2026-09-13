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

## Where the credential lives

Outside the workspace, under the runner temp directory.

`google-github-actions/auth` writes `gha-creds-<random>.json` into
`$GITHUB_WORKSPACE` and offers no input to move it — the path is built from
that variable, and `credentials_file_path` is an output rather than an input.
The file is untracked, no `.gitignore` in this organisation names `gha-creds`,
and the action's post step removes it only at the end of the job.

That matters because a step's output is defined as everything git reports as
untracked or ignored, on purpose: no list decides what counts, so the file
nobody thought to list is still captured. A credential inside the workspace
would therefore be captured and published by construction. So this action
overrides `GITHUB_WORKSPACE` for the auth step alone, which is the only thing
that variable decides there, and the credential lands somewhere a capture will
not look.

The alternative — teaching every capture to exclude `gha-creds-*.json` —
reinstates the maintained list the arrangement exists to remove, and its
omissions would disclose a credential rather than merely lose a file.

Consumers need to know nothing about this: `GOOGLE_APPLICATION_CREDENTIALS`
and `GOOGLE_GHA_CREDS_PATH` point at the relocated file, and the upstream
cleanup step removes the path it actually wrote.

`no-credential-in-workspace.sh` runs afterwards and fails the job if a
credential is in the workspace anyway, if none was created at all, or if the
reported path is inside the workspace. The relocation depends on an
implementation detail of a pinned third-party action, so a version bump that
changes it fails here rather than in whatever captures the workspace next.

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
