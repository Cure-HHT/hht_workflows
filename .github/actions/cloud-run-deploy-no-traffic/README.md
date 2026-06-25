# cloud-run-deploy-no-traffic

Deploys a Cloud Run (v1) service revision with `--no-traffic` + a revision tag.
Live traffic stays on the prior revision; the new revision is reachable only at
its tagged URL for verification. Pair with `cloud-run-migrate-traffic` to
promote after a passing smoke.

## Usage

Prerequisites: the job must be authenticated to GCP (e.g.
`google-github-actions/auth`), have the gcloud CLI on PATH (e.g.
`google-github-actions/setup-gcloud`), and have `jq` available (preinstalled on
GitHub-hosted `ubuntu-*` runners). Pin by commit SHA.

    - id: canary
      uses: Cure-HHT/hht_workflows/.github/actions/cloud-run-deploy-no-traffic@<sha>
      with:
        service: portal-service
        region: europe-west9
        project: callisto4-dev
        image: europe-west9-docker.pkg.dev/.../portal-final@sha256:...
        cloudsql_instances: callisto4:europe-west9:callisto4-dev-db-503e
        vpc_connector: callisto4-dev-vpc-con
        update_env_vars: "ENVIRONMENT=dev,SPONSOR_ID=callisto,..."
        remove_env_vars: "DOPPLER_TOKEN"
    # steps.canary.outputs.tagged_url / .revision_name

## Inputs / Outputs

See `action.yml`. `update_env_vars` may carry a secret on legacy paths and is
never echoed.
