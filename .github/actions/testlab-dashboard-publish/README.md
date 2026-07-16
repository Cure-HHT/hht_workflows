# testlab-dashboard-publish

Publishes Firebase Test Lab run results to the `testlab-dashboard` repo
as a `dashboard_data.json` commit. Best-effort: every stage degrades to a
warning and `published=false` rather than failing the job.

## Usage

    # GCP auth (Tool Results API) — reuse the job's WIF credentials:
    - uses: Cure-HHT/hht_workflows/.github/actions/gcp-wif-auth@<sha>
      with:
        workload_identity_provider: ${{ vars.WIF_PROVIDER }}
        service_account: ${{ vars.WIF_SA }}

    # Mint the short-lived App token (key fetched from Doppler admin/prod
    # via OIDC; see hht_diary's firebase-test-lab.yml for the full recipe):
    - uses: actions/create-github-app-token@<sha>
      id: dashboard-token
      with:
        app-id: ${{ vars.MANIFEST_GH_APP_CLIENT_ID }}
        private-key: ${{ env.MANIFEST_GH_APP_PRIVATE_KEY }}
        owner: ${{ github.repository_owner }}
        repositories: testlab-dashboard
        permission-contents: write

    - uses: Cure-HHT/hht_workflows/.github/actions/testlab-dashboard-publish@<sha>
      with:
        gcp_project_id: cure-hht-qa
        token: ${{ steps.dashboard-token.outputs.token }}
        evidence_dirs: |
          evidence/android
          evidence/ios
        commit_context: "run ${{ github.run_id }}, qa/android"
        # Optional (defaults shown):
        # dashboard_repository: Cure-HHT/testlab-dashboard
        # dashboard_ref: initial-import
        # dashboard_data_path: testlab-dashboard-main/dashboard_data.json

## Required workflow permissions

    permissions:
      id-token: write    # WIF + (in the caller) Doppler OIDC for the App key
      contents: read

## Token requirements

`token` MUST be a per-job GitHub App installation token minted from
`cure-hht-ops-bot`, scoped to the single dashboard repo with
`contents: write` only (`HHT-OPS-cicd-app-operations/B,J`). Personal
access tokens are prohibited (`HHT-OPS-identity-over-keys/C`,
`HHT-OPS-cicd-app-operations/I`).

## What it does

1. Sets up the gcloud SDK (SHA-pinned `setup-gcloud`).
2. Recovers the Test Lab history/execution IDs from the
   `gcloud-output.log` console-URL banner in the given evidence dirs
   (bundled `extract_test_lab_ids.py`).
3. Fetches the run's device/test outcomes from the Tool Results API with
   the job's existing gcloud credentials and assembles the dashboard's
   data shape (bundled `fetch_toolresults.py`, a CI-side port of the
   dashboard's own browser `fetchLive()`).
4. Checks out the dashboard repo with `token` and commits the new
   `dashboard_data.json` (no commit when the data is unchanged).
5. Appends a publish table to the job summary.

Outputs: `published` (`'true'`/`'false'`), `history_id`, `execution_id`.

## Why this exists

Part of the org composite-action library
(`HHT-OPS-composite-action-library`). Replaces the previous PAT-based
push in `hht_diary`'s Firebase Test Lab workflow with the canonical
`cure-hht-ops-bot` publish-artifact write pattern
(`HHT-OPS-cicd-app-operations/J`).
