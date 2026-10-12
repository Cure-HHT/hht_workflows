# download-integrity

Refuses a build definition that downloads a file without verifying it.

**Why this exists:** `HHT-OPS-ci-tool-download-integrity` (hht_admin
`spec/ops-cicd.md`). A release asset or CDN response that has been replaced
upstream runs inside the build with the build's credentials. A version pin
names what the build means to fetch; only a verification proves the bytes are
those bytes.

## What it checks

Container build files (`Dockerfile*`, `*.Dockerfile`, `Containerfile*`,
`*.containerfile`, any case), GitHub workflows, composite actions, and
workflow templates (`*.yml.template`, which become workflows in the
repositories they are copied into). Under pre-commit it checks the changed
files; when `.github/versions.env` is among them it checks every container
build file too, since a changed pin can put any Dockerfile's digest default
out of step.

The unit is one Dockerfile `RUN` or one workflow step's `run:` script. The
script is split into pipelines (quote-aware; comments dropped; command and
process substitutions and heredocs fed to a shell included), and each
download is matched to a verification **of that file**.

### A download

`curl` or `wget` fetching a non-local URL that:

- pipes into an extractor, installer or key tool (`tar`, `unzip`, `gpg
  --import`/`--dearmor`, `apt-key`, `dpkg`, ...) -- always a finding, since
  nothing can check bytes that are already in use;
- or writes a file (`-o`, `-O`, `--output`, wget's default, `>`/`>>`,
  `| tee FILE`, `| dd of=FILE`) whose name is an archive, package, script or
  binary (`.tgz .tar.* .zip .deb .rpm .sh .whl .gz .xz .bz2 .AppImage`, ...) or
  has no extension, a file under a `keyrings`/`trusted.gpg.d` directory, or a
  checksum list. These count even when nothing in the same step uses the file,
  so a download cannot escape by being used in the next step;
- or writes any other file that the step then extracts, installs, copies or
  runs.

Not a download: a file whose name is data (`.json .xml .txt .html .md` ...)
that nothing in the step runs, and a request that sends data or reads only its
status (`-X POST`, `-d`, `-F`, `-w`) -- an API reply kept as evidence, a
health probe.

The URL may be literal or held in a variable that the step, the Dockerfile's
`ARG`/`ENV`, or the workflow/job/step `env:` map assigns a URL. In a workflow
or composite action, a URL whose value the file does not show (`"$VAR"`,
`${{ inputs.url }}`) also counts: the caller decides it.

### A verification

A real command invocation -- `echo "...sha256sum -c..."`, `: verify-download`
or a mention of an install script is not one:

- `sha256sum -c` / `shasum -a 256 -c`, fed on stdin by `echo`/`printf`/`<<<` of
  a literal or variable digest and the file name, or given a checksum file that
  was not downloaded (for example one written from a recorded digest);
- hht_diary's `verify-download sha256|key`;
- `cosign verify-blob`, `gpg --verify`, `gpgv`.

It counts for a download only if it **names that file**, comes **before the
first command that uses the file**, and is **not followed by `||`** (which lets
the step carry on when the check fails; reported against assertion B).
`if ! ...; then exit 1; fi` is the form to use.

### Signatures and checksum lists

A detached signature (`.sig`, `.asc`, `.bundle`, `.sigstore`) fetched to a
file is verification material, not a download, only when a `gpg --verify`,
`gpgv` or `cosign verify-blob` in the step names it. Otherwise -- a signing
key fetched as `.asc` and then dearmored -- it is a download and needs its own
check (`verify-download key FILE FINGERPRINT`).

A checksum list fetched beside the asset is a download, and a check fed from
it verifies nothing: it proves the download is intact, not authentic, because
whoever can replace the asset can replace the checksum file. It becomes
usable only when the checksum list is itself verified (a pinned-key signature
on it).

### Always refused

- A download run by an interpreter: `curl ... | sh` (also through `env`,
  `sudo -E`, `xargs`), `bash <(curl ...)`, `sh -c "$(curl ...)"`,
  `eval "$(curl ...)"`, `source <(curl ...)`. Nothing can check it before it
  runs, and no exemption covers it.
- `ADD <url>` in a Dockerfile without `--checksum=sha256:...`.
- A step that `uses:` an action known to run an unverified vendor installer.
  The list is `UNVERIFIED_INSTALLER_ACTIONS` in the hook; today it holds
  `dopplerhq/cli-action` (it runs `cli.doppler.com/install.sh` unchecked), and
  the finding names the replacement, this repository's `install-doppler-cli`.

### Pins

Every `*_SHA256` in `.github/versions.env` must be a well-formed digest, and
a Dockerfile's own `ARG *_SHA256` default (what a build with no build-args
uses), and the `ARG *_VERSION` beside it, must equal `versions.env`.

The check proves a verification is present, not that it is correct.

## Findings

Each finding names the assertion of `HHT-OPS-ci-tool-download-integrity` it
breaks: `/A` for an unverified, late, mis-named or same-origin-checked
download, a run-by-interpreter download, a denied action, and a malformed or
drifted recorded digest; `/B` for a verification followed by `||`. A workflow
whose YAML does not parse is reported as `cannot check`, with no assertion.

## Exceptions

Write the reason into the unit itself, as a whole comment line (not a trailing
comment and not text inside a string), naming the ticket that tracks it:

```text
# download-integrity: exempt <reason> CUR-NNNN
```

A marker without a `CUR-` ticket is ignored. An exception never covers a
download run by an interpreter.

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

Run it by hand over a whole repository with `download-integrity` (no
arguments) from its root, or `download-integrity --root <dir>`, or
`python -m download_integrity --root <dir>`.

## Tests

```sh
pip install -e '.[test]'
pytest hooks/download-integrity/tests/ -v
```
