# cloud-run-resolve-serving-digest

Reads the image digest a Cloud Run (v1) service is **currently serving to all
traffic**, so a promotion advances the artifact the source environment actually
proved rather than whatever a mutable tag points at now. Pair with the deploy
path to promote that digest into the next environment.

## Why not just read the latest revision

The deploy path publishes each revision with `--no-traffic` and migrates traffic
only after verification passes, so the newest revision is frequently *not* the
one serving: a deploy that failed between publication and migration leaves a
newer revision that was never live. Reading `latestCreatedRevisionName` would
promote bytes the environment never ran.

## Refusals

The action refuses rather than guessing when:

- traffic is split across more than one revision — no single artifact is what the
  environment proved;
- no revision is drawing traffic at all;
- the lone revision drawing traffic holds less than 100% (a rollout in progress);
- the reference read back is not pinned to an immutable content digest.

The last is also an injection guard: the reference is a server-supplied string
that flows into later command text, and the shape check is anchored at both ends
so a trailing shell fragment cannot survive as a "valid enough" prefix.

## Usage

Prerequisites: the job must be authenticated to GCP (e.g.
`google-github-actions/auth`), have the gcloud CLI on PATH (e.g.
`google-github-actions/setup-gcloud`), and have `jq` available (preinstalled on
GitHub-hosted `ubuntu-*` runners). Reading a *source* environment's state means
the job's identity needs `roles/run.viewer` (or broader) on that environment's
project, which is a different project from the deploy target. Pin by commit SHA.

    - id: source
      uses: Cure-HHT/hht_workflows/.github/actions/cloud-run-resolve-serving-digest@<sha>
      with:
        service: portal-service
        region: <region>
        project: <source-env-project-id>
    # steps.source.outputs.image_digest  -> ...portal-final@sha256:<64-hex>
    # steps.source.outputs.revision_name -> portal-service-00042-abc

## Inputs / Outputs

See `action.yml`.

## Tests

`tests/test_resolve_logic.py` extracts the resolve step straight out of
`action.yml` and runs it against a stub `gcloud` fed the recorded API responses
in `tests/fixtures/resolve-serving-digest/` at the repo root, asserting the exit
code and the specific `::error::` message for every path above. Split traffic in
particular is only reachable this way — a live service cannot readily be asked to
split its traffic just to watch a refusal.

    pytest .github/actions/cloud-run-resolve-serving-digest/tests/ -v
