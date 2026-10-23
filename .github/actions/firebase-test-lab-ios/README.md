# firebase-test-lab-ios

Runs an iOS XCTest matrix on Firebase Test Lab with catalog-aware device
resolution and infrastructure-error retries, without failing the job on a
matrix result.

## Usage

    - uses: Cure-HHT/hht_workflows/.github/actions/gcp-wif-auth@<sha>
      with:
        workload_identity_provider: ${{ vars.WIF_PROVIDER }}
        service_account: ${{ vars.WIF_SA }}

    - uses: Cure-HHT/hht_workflows/.github/actions/firebase-test-lab-ios@<sha>
      id: ftl
      with:
        gcp_project_id: cure-hht-qa
        flavor: qa
        xctest_zip: build/firebase-test-lab/ios/ios-qa-xctest.zip
        results_dir: my-run/${{ github.run_id }}/${{ github.run_attempt }}
        evidence_dir: build/firebase-test-lab/ios/evidence
        working_directory: apps/daily-diary/clinical_diary
        # Optional:
        # devices: model=iphone16pro,version=18.3,locale=en_US,orientation=portrait
        #   (explicit override; blank resolves from device_fallbacks)
        # timeout: 30m
        # results_bucket: ${{ vars.FIREBASE_TEST_LAB_RESULTS_BUCKET }}
        # devices_exclude: 'iphonese3'
        # device_fallbacks: 'iphonese3:18.4 iphone16pro:18.3'
        # xcode_version: '16.4'
        # max_attempts: '3'
        # test_target: integration_test/my_smoke_test.dart

    # ... upload evidence artifacts here ...

    - name: Enforce iOS matrix result
      if: always()
      env:
        EXIT_CODE: ${{ steps.ftl.outputs.exit_code }}
      run: |
        if [ -z "${EXIT_CODE:-}" ]; then
          echo "::error::matrix did not execute."; exit 1
        fi
        if [ "$EXIT_CODE" -eq 15 ] || [ "$EXIT_CODE" -eq 20 ]; then
          echo "::warning::infrastructure/inconclusive after retries; not failing."; exit 0
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
   Lab device catalog into `evidence_dir`.
3. Splits explicit `devices` on newlines, whitespace, or semicolons; otherwise resolves the
   first available, non-deprecated, version-supported device from
   `device_fallbacks` against the live catalog. Errors when neither
   yields a device; records the choice in
   `evidence_dir/selected-device.txt` and the `devices` output.
4. Runs the matrix via the bundled `run-ios-test-lab.sh`, retrying only
   Test Lab infrastructure/inconclusive results (exit 15 or 20) up to
   `max_attempts` times — each attempt in its own results dir and
   evidence subdir, with the final attempt mirrored to the top-level
   evidence paths.
5. Appends a result table to the job summary.

The matrix result is **captured, not enforced**: `exit_code` and
`attempts` are exposed as outputs so the caller can upload evidence
artifacts first and fail the job last (typically downgrading a
post-retry exit 15 to a warning).

## Why this exists

Part of the org composite-action library
(`HHT-OPS-composite-action-library`): Test Lab execution is org-generic
CI logic; consumer repos keep only thin dispatchers. Consumers annotate
their calling step with their own REQ traceability (e.g.
`DIARY-OPS-automated-test-execution/B` in `hht_diary`).
