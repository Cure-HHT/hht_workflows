# install-doppler-cli

Installs the Doppler CLI from its GitHub release after verifying Doppler's
signature on the release tarball.

**Why this exists:** `HHT-OPS-ci-tool-download-integrity/A+B`. The vendor
installer, `curl https://cli.doppler.com/install.sh | sudo sh`, runs a
downloaded script as root before anything can check it. This action installs
only a tarball whose detached signature verifies against the Doppler CLI
release key shipped in this directory (`doppler-cli-release.asc`, primary
fingerprint `B70BD7FCA460C4A3D0EEB965D3D593D50EE79DEC`). The fingerprint is
pinned in `install.sh`, so a replaced key file is refused as well.

## Usage

    - uses: Cure-HHT/hht_workflows/.github/actions/install-doppler-cli@<sha>
      with:
        version: ${{ env.DOPPLER_CLI_VERSION }}   # X.Y.Z; a leading v is accepted

Then authenticate it with `doppler-cli-oidc-auth`. The version has no default:
read it from the caller's `versions.env`.

Signature verification covers any Doppler release, so a version bump needs no
change here. The release key expires on 2029-10-29; when Doppler rotates it,
update `doppler-cli-release.asc` and the pinned fingerprint together.

## Runners

Linux x86_64 only: the action fetches the linux amd64/x64 release asset. On any
other architecture it fails before downloading anything. The binary's
reported version is checked in the work directory, before it is installed.

## Tests

`tests/install_test.sh` drives every refusal path offline (tampered tarball,
signature by another key, swapped key file, malformed version, missing
release). The `install-doppler-cli` readiness job installs a real release.
