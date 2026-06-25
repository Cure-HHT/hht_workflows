# cloud-run-migrate-traffic

Routes 100% of a Cloud Run (v1) service's traffic to a named revision, after the
caller has verified that revision (typically one staged by
`cloud-run-deploy-no-traffic`). Targets an explicit revision, not LATEST. Pin by
commit SHA.

## Usage

Prerequisites: the job must be authenticated to GCP (e.g.
`google-github-actions/auth`) and have the gcloud CLI on PATH (e.g.
`google-github-actions/setup-gcloud`).

    - uses: Cure-HHT/hht_workflows/.github/actions/cloud-run-migrate-traffic@<sha>
      with:
        service: portal-service
        region: europe-west9
        project: callisto4-dev
        revision: ${{ steps.canary.outputs.revision_name }}
