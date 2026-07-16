# firebase-test-lab-android

Runs an Android instrumentation matrix on Firebase Test Lab and captures
evidence, without failing the job on a matrix result.

## Usage

    - uses: Cure-HHT/hht_workflows/.github/actions/gcp-wif-auth@<sha>
      with:
        workload_identity_provider: ${{ vars.WIF_PROVIDER }}
        service_account: ${{ vars.WIF_SA }}

    - uses: Cure-HHT/hht_workflows/.github/actions/firebase-test-lab-android@<sha>
      id: ftl
      with:
        gcp_project_id: cure-hht-qa
        flavor: qa
        app_apk: build/firebase-test-lab/android/app-qa-debug.apk
        test_apk: build/firebase-test-lab/android/app-qa-debug-androidTest.apk
        results_dir: my-run/${{ github.run_id }}/${{ github.run_attempt }}
        evidence_dir: build/firebase-test-lab/android/evidence
        working_directory: apps/daily-diary/clinical_diary
        # Optional:
        # timeout: 30m
        # results_bucket: ${{ vars.FIREBASE_TEST_LAB_RESULTS_BUCKET }}
        # devices: |
        #   model=shiba,version=35,locale=en,orientation=portrait
        # devices_exclude: 'r0q a10'
        # use_orchestrator: 'true'
        # flaky_test_attempts: '1'
        # test_target: integration_test/my_smoke_test.dart

    # ... upload evidence artifacts here ...

    - name: Enforce Android matrix result
      if: always()
      env:
        EXIT_CODE: ${{ steps.ftl.outputs.exit_code }}
      run: |
        if [ -z "${EXIT_CODE:-}" ]; then
          echo "::error::matrix did not execute."
          exit 1
        fi
        exit "$EXIT_CODE"

## Required workflow permissions

    permissions:
      id-token: write    # for the preceding WIF auth
      contents: read

## What it does

1. Sets up the gcloud SDK (SHA-pinned `setup-gcloud`); GCP auth must
   already exist (use `gcp-wif-auth` first).
2. Verifies the active gcloud identity and project, and writes the Test
   Lab device catalog (`models.json`, `versions.json`) into
   `evidence_dir`.
3. Runs the matrix via the bundled `run-android-test-lab.sh` (default
   coverage matrix of physical + virtual devices unless `devices` is
   set), logging the exact gcloud command, output, and exit code into
   `evidence_dir`, and downloading the raw result tree when
   `results_bucket` is set.
4. Appends a result table to the job summary.

The matrix result is **captured, not enforced**: `exit_code` is exposed
as an output (0 pass, 10 test failures, 15 infrastructure, 19 canceled)
so the caller can upload evidence artifacts first and fail the job last.

## Why this exists

Part of the org composite-action library
(`HHT-OPS-composite-action-library`): Test Lab execution is org-generic
CI logic; consumer repos keep only thin dispatchers. Consumers annotate
their calling step with their own REQ traceability (e.g.
`DIARY-OPS-automated-test-execution/B` in `hht_diary`).
