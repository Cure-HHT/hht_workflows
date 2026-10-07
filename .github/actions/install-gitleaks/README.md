# install-gitleaks

Installs gitleaks from its GitHub release after checking the tarball against
the SHA-256 recorded for that version in `digests`.

**Why this exists:** `HHT-OPS-ci-tool-download-integrity/A+B`, and the
requirement that the gitleaks download exist in one place
(`HHT-OPS-composite-action-library/A+E`). `secrets-scan` installs through this
action's script, and any workflow that runs gitleaks itself should use this
action rather than downloading it.

gitleaks publishes only a checksum file beside its release assets. A digest
read from that file at install time proves the download is intact, not that it
is authentic, so the digest is recorded here when a version is added and every
later download must match it.

## Usage

    - uses: Cure-HHT/hht_workflows/.github/actions/install-gitleaks@<sha>
      with:
        version: ${{ env.GITLEAKS_VERSION }}

A version with no line in `digests` is refused. To move to a new gitleaks, add
`<version> <sha256>` to `digests` (from the release's checksums file, confirmed
against a downloaded copy), release this repository, and re-pin consumers. The
optional `sha256` input lets a caller assert the digest it expects; it must
agree with `digests` and cannot admit an unrecorded version.

## Tests

`tests/install_test.sh` covers the refusal paths offline. The
`install-gitleaks` readiness job installs the real release and proves a
disagreeing digest is refused.
