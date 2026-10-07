# download-integrity

Refuses a build definition that downloads a file without verifying it.

**Why this exists:** `HHT-OPS-ci-tool-download-integrity` (hht_admin
`spec/ops-cicd.md`). A release asset or CDN response that has been replaced
upstream runs inside the build with the build's credentials. A version pin
names what the build means to fetch; only a verification proves the bytes are
those bytes.

## What it checks

Container build files (`Dockerfile`, `*.Dockerfile`, `Dockerfile.*`), GitHub
workflows, composite actions, and workflow templates (`*.yml.template`, which
become workflows in the repositories they are copied into).

In each unit of execution (a Dockerfile `RUN`, a workflow step's `run:`
script) it counts the downloads and the verifications, and fails the unit if
there are more downloads than verifications.

**A download** is `curl` or `wget` fetching a non-local URL into a pipe that
feeds a shell, archiver or key tool, or into a file in a unit that then
unpacks, installs or runs something. A URL assembled in a shell variable
(`base="https://..."`, then `"$base/$asset"`) counts. An API reply kept as data
does not.

**A verification** is `sha256sum -c`, `cosign verify-blob`, `gpg --verify`,
hht_diary's `verify-download`, or this repository's
`install-doppler-cli` / `install-gitleaks` scripts.

**Not a verification:** a checksum file downloaded beside the asset. It proves
the download is intact, not authentic, because whoever can replace the asset
can replace the checksum file too. Verify against a digest recorded in the
repository, or a signature checked against a pinned signing key.

**Always refused:** a download piped straight into an interpreter
(`curl ... | sh`). Nothing can check it before it runs.

It also checks that every `*_SHA256` in `.github/versions.env` is a
well-formed digest, and that a Dockerfile's own `ARG *_SHA256` default (what a
build with no build-args uses) equals `versions.env`.

The check proves a verification is present, not that it is correct.

## Exceptions

Write the reason into the unit itself, so it travels with the code and is
visible in review:

```text
# download-integrity: exempt <reason, and the ticket tracking it>
```

## Usage in a consumer repo

`.pre-commit-config.yaml`:

```yaml
  - repo: https://github.com/Cure-HHT/hht_workflows
    rev: <commit-sha>  # vX.Y.Z
    hooks:
      - id: download-integrity
```

and in CI, so a bypassed local hook still cannot land a change:

```yaml
      - uses: actions/checkout@<sha>
      - uses: Cure-HHT/hht_workflows/.github/actions/download-integrity-check@<commit-sha>
```

Run it by hand over a whole repository with
`download-integrity` (no arguments) or `download-integrity --root <dir>`.

## Tests

```sh
pip install -e '.[test]'
pytest hooks/download-integrity/tests/ -v
```
