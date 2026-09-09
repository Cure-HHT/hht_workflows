# Free Disk Space

Composite action that removes the preinstalled tooling a stock GitHub-hosted
runner ships with (~30 GB), freeing `/` before a large `docker build`.

## Why

The portal-final image's base (`sponsor-ci`) carries a full Dart `.pub-cache`
that unpacks into Docker's data root on `/`. On a stock `ubuntu-22.04` runner
(~14 GB free) that overflows mid-build:

```
failed to register layer: write .../.pub-cache/.../googleapis-.../...: no space left on device
```

This cleanup previously lived only inline in
`hht_sponsor_iac/.github/workflows/sponsor-build-template.yml` (CUR-1987). The
sponsor `hotfix-deploy.yml` build path builds independently and never received
it, so it kept failing (CUR-1988). This action is the single source both paths
invoke, so they cannot drift.

## Usage

Invoke after checkout and before the `docker build`:

```yaml
- uses: actions/checkout@v7
- uses: Cure-HHT/hht_workflows/.github/actions/free-disk-space@<sha>
- name: Build image
  run: docker build ...
```

Pin by full commit SHA (org convention — see `cosign-verify/README.md`). No
inputs.

## What it removes

`/opt/hostedtoolcache`, `/usr/share/dotnet`, `/opt/ghc`,
`/usr/local/lib/android`, `/usr/local/share/boost`, `/usr/share/swift`,
`/usr/local/lib/node_modules`, plus a `docker image/container prune`. It prints
`df -h /` before and after.
