# setup-pub-git-auth

Authenticates a CI job to **private Cure-HHT git dependencies** (the
`event_sourcing` / `reaction` / `reaction_widgets` / `reaction_widgets_testing`
packages that diary/portal consume via `git:` deps) so `dart pub get` /
`flutter pub get` can resolve them — without deploy keys or static PATs.

It mints a short-lived **ops-bot GitHub App installation token** and rewrites
`git@github.com:<owner>/` URLs to `https://x-access-token:<token>@github.com/<owner>/`
for the duration of the job.

## Usage

    jobs:
      build:
        runs-on: ubuntu-latest
        permissions:
          id-token: write   # required by the Doppler OIDC exchange below
          contents: read
        steps:
          - uses: actions/checkout@v4

          # 1. Fetch the ops-bot App key from Doppler via OIDC (no static token).
          - uses: Cure-HHT/hht_workflows/.github/actions/doppler-oidc-auth@<sha>
            with:
              doppler_identity_id: ${{ vars.DOPPLER_IDENTITY_ID }}
              doppler_project:     ${{ vars.DOPPLER_PROJECT }}    # e.g. admin
              doppler_config:      ${{ vars.DOPPLER_CONFIG }}     # e.g. prd

          # 2. Mint the App token and rewrite git@ URLs. The App key arrives as
          #    masked env vars from step 1 (names match the Doppler secrets).
          - uses: Cure-HHT/hht_workflows/.github/actions/setup-pub-git-auth@<sha>
            with:
              app_id:          ${{ env.OPS_BOT_APP_ID }}
              app_private_key: ${{ env.OPS_BOT_APP_PRIVATE_KEY }}
              # owner defaults to Cure-HHT; repositories defaults to event_sourcing

          # 3. Now pub can resolve the private git deps.
          - run: flutter pub get
            working-directory: apps/daily-diary/clinical_diary

## Inputs

| Input             | Required | Default          | Description |
|-------------------|----------|------------------|-------------|
| `app_id`          | yes      | —                | ops-bot GitHub App ID (from Doppler via `doppler-oidc-auth`). |
| `app_private_key` | yes      | —                | ops-bot App private key PEM (from Doppler). |
| `owner`           | no       | `Cure-HHT`       | Org that owns the private dependency repos. |
| `repositories`    | no       | `event_sourcing` | Comma-separated repos (within `owner`) the token may read. |

## Outputs

| Output  | Description |
|---------|-------------|
| `token` | The minted short-lived installation token (masked); expires with the job. |

## Required workflow permissions

    permissions:
      id-token: write   # for the doppler-oidc-auth step that feeds this action
      contents: read

## What it does

1. `actions/create-github-app-token` (pinned by SHA, `v3.2.0`) mints an
   installation token scoped to `owner` + `repositories` with `contents: read`
   only. This requires the ops-bot App to be **installed on those repos**.
2. Configures `git`'s `insteadOf` for `owner` so both the SSH form
   (`git@github.com:<owner>/`) and the plain-HTTPS form resolve through the
   token. `pub` shells out to the system `git`, so this is all it needs.

The token is short-lived (App installation tokens expire in ~1 hour) and the
runner is ephemeral, so no explicit teardown is required.

## Why this exists

Implements `HHT-OPS-identity-over-keys/B` and
`HHT-OPS-composite-action-library/A,B` from
`Cure-HHT/hht_admin/spec/ops-secrets-architecture.md`: git auth is a per-job
ephemeral identity (an App installation token minted from the OIDC-fetched App
key), not a static deploy key or PAT, and the handshake is implemented once here
and consumed by reference so the pin/upgrade lives in one place.

The diary and portal apps consume `event_sourcing` as private `git:` deps; every
CI job that runs `pub get` (and the SonarCloud scan) needs this before resolution
or the analyzer reports the imports as unresolvable. Centralizing it here means
all consumers share one mechanism.

## Breaks if

- The workflow lacks `permissions: id-token: write` (the upstream
  `doppler-oidc-auth` step cannot mint its token).
- The ops-bot App is **not installed** on the `repositories` (e.g.
  `event_sourcing`), or lacks `contents: read` there — token mint fails or the
  token cannot read the repo.
- `app_id` / `app_private_key` are empty (the `doppler-oidc-auth` step did not
  run, or the Doppler secret names differ from `OPS_BOT_APP_ID` /
  `OPS_BOT_APP_PRIVATE_KEY` — adjust the `with:` values to your secret names).
- A consumer pins a `git:` dep to an owner other than `owner` (add it to a
  second invocation or extend `repositories`).
