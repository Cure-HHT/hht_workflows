#!/usr/bin/env python3
"""download-integrity: refuse a build definition that downloads a file without verifying it.

Pre-commit hook (and, through the download-integrity-check action, a CI check)
distributed from cure-hht/hht_workflows. Scans container build files
(Dockerfile, *.Dockerfile, Dockerfile.*), GitHub workflows, composite actions,
and workflow templates (*.yml.template / *.yaml.template, which become workflows
in the repositories they are copied into). Run by pre-commit it checks the files
pre-commit passes; run with no file arguments it checks every tracked file. Within each unit
of execution -- a Dockerfile RUN, a workflow step's `run:` script -- it counts
the downloads that land somewhere they can be used, and the verifications of a
downloaded file, and fails the unit if there are more downloads than
verifications.

What counts as a download: `curl` or `wget` fetching a non-local http(s) URL
into a pipe feeding a shell, archiver, or key tool; or into a file, in a unit
that also unpacks, installs, or runs something (tar, unzip, install, chmod +x,
gpg --dearmor, dpkg -i, sh <file>, ...). A response that is only kept as data
-- an API reply saved as evidence, a health probe -- is not a tool and is not
counted: the requirement governs what the build executes.

What counts as a verification:
  - `sha256sum -c` / `sha256sum --check`
  - `verify-download sha256|key` (hht_diary's dev-env helper)
  - `cosign verify-blob`, `gpg --verify`
  - the install-doppler-cli / install-gitleaks scripts of this repository

What does not: a checksum file downloaded in the same unit. A digest fetched
from the same release as the asset proves the download is intact, not that it
is authentic -- whoever can replace the asset can replace the checksum file.
Each such download cancels one verification in its unit.

A download piped straight into a shell interpreter can never be verified before
it runs, so it fails regardless of any verification elsewhere in the unit.
`ADD <url>` in a Dockerfile passes only with `--checksum=sha256:...`.

It also checks that every digest recorded in .github/versions.env is a
well-formed SHA-256, and that a Dockerfile which carries its own default for a
digest (because `docker compose build` passes no build-args) carries the same
value, and the same version, as versions.env.

This proves a verification is present, not that it is correct. Its job is to
stop the unverified-download class from coming back.

An exception, where one is ever warranted, is written into the unit itself:
    # download-integrity: exempt <reason>
so the reason travels with the code and is visible in review.

Exit 0 when clean, 1 with one line per finding otherwise.
"""
# Implements: HHT-OPS-ci-tool-download-integrity/C

from __future__ import annotations

import dataclasses
import pathlib
import re
import subprocess
import sys

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - environment problem, not a finding
    print("download-integrity: needs PyYAML", file=sys.stderr)
    raise SystemExit(2)

VERSIONS_ENV = ".github/versions.env"
EXEMPT = re.compile(r"#\s*download-integrity:\s*exempt\s+\S")

# A URL we would have to trust. Loopback, link-local and the metadata server
# are the local machine or the platform itself, not a download.
_URL = re.compile(r"""https?://(?!(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|169\.254\.169\.254|metadata\.google\.internal)[:/"'\s])[^\s"'|;&)]+""")
_FETCHER = re.compile(r"(?<![\w-])(curl|wget)(?![\w-])")
_SHELL_SINK = re.compile(r"^\s*(?:sudo\s+(?:-\S+\s+)*)?(?:ba|z|da)?sh\b|^\s*(?:sudo\s+)?(?:python3?|perl|ruby|node)\b")
_FILE_SINK = re.compile(r"^\s*(?:sudo\s+(?:-\S+\s+)*)?(?:tar|unzip|gpg|gpg2|apt-key|dd|tee|install|cat\s*>|funzip|xz|gunzip|bsdtar)\b")
_VERIFY = re.compile(
    r"sha256sum\s+(?:[^|;&\n]*\s)?(?:-c|--check)\b"
    r"|\bverify-download\s+(?:sha256|key)\b"
    r"|\bcosign\s+verify-blob\b"
    r"|\bgpg2?\s+(?:[^|;&\n]*\s)?--verify\b"
    r"|install-(?:doppler-cli|gitleaks)/install\.sh\b"
)
# A detached signature: verification material checked against a pinned key, not
# a tool, so fetching it is not a download the unit must verify.
_SIGNATURE_FILE = re.compile(r"\.(?:sig|asc|sigstore|bundle)(?:[\"'\s]|$)")
# A checksum list fetched beside the asset it describes.
_CHECKSUM_FILE = re.compile(r"(?:checksums?(?:\.txt)?|SHA256SUMS|sha256sums(?:\.txt)?|\.sha256(?:sum)?)(?:[\"'\s]|$)", re.I)
# Something in the unit turns a downloaded file into code that runs.
_USE = re.compile(
    r"(?<![\w-])(?:tar|unzip|bsdtar|install|dpkg|rpm|gpg2?|apt-key|pip3?|npm)\s"
    r"|chmod\s+(?:[0-7]*[1357]\b|[ugoa]*\+[rw]*x)"
    r"|(?<![\w-])(?:ba|z|da)?sh\s+[^-\s]"
    r"|(?<![\w-])python3?\s+[^-\s]"
)
_ADD_URL = re.compile(r"^\s*ADD\s+(?P<flags>(?:--\S+\s+)*)(?P<src>https?://\S+)", re.I)


@dataclasses.dataclass(frozen=True)
class Finding:
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        # The Merge Check names the assertion each finding breaks
        # (HHT-OPS-merge-checked-rule/C). Every finding here is a download that
        # is not verified before use.
        return f"{self.path}:{self.line}: {self.message} [breaks HHT-OPS-ci-tool-download-integrity/A]"


# ---------------------------------------------------------------- shell units


def _commands(script: str) -> list[str]:
    """Split a shell script into pipelines, joined across continuations.

    Comments are dropped first so a URL in a comment is not a download.
    Splits on newlines and on && / || / ; so each element is one pipeline.
    """
    lines = []
    for raw in script.replace("\\\n", " ").splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("#"):
            continue
        lines.append(raw)
    text = "\n".join(lines)
    return [c for c in re.split(r"\n|&&|\|\||;", text) if c.strip()]


_URL_ASSIGN = re.compile(r"""^\s*(?:export\s+|local\s+|readonly\s+)?([A-Za-z_][A-Za-z0-9_]*)=["']?https?://""")


def _url_vars(commands: list[str]) -> set[str]:
    """Shell variables assigned a URL earlier in the unit (base="https://...")."""
    return {m.group(1) for c in commands for m in [_URL_ASSIGN.match(c)] if m}


def _has_url(text: str, url_vars: set[str]) -> bool:
    if _URL.search(text):
        return True
    return any(re.search(r"\$\{?" + re.escape(v) + r"\b", text) for v in url_vars)


def _is_download(pipeline: str, url_vars: set[str] = frozenset()) -> tuple[bool, bool]:
    """Return (is_download, piped_to_shell) for one pipeline."""
    stages = pipeline.split("|")
    first = stages[0]
    m = _FETCHER.search(first)
    if not m or not _has_url(first, url_vars):
        return False, False
    tool = m.group(1)
    rest = stages[1:]
    if rest and _SHELL_SINK.search(rest[0]):
        return True, True
    if rest and _FILE_SINK.search(rest[0]):
        return True, False
    args = first[m.end():]
    if tool == "curl":
        # Output written to a file (-o, -O, --output, --remote-name, or a
        # combined short-flag cluster ending in o/O such as -fsSLo).
        writes_file = re.search(r"(?:^|\s)(?:-[a-zA-Z]*[oO]\b|--output\b|--remote-name\b|--output-dir\b)", args)
        return bool(writes_file), False
    # wget writes a file unless told to write to stdout (-O - / -qO- / -O-).
    to_stdout = re.search(r"(?:^|\s)-[a-zA-Z]*O\s*-(?:\s|$)|--output-document(?:=|\s+)-(?:\s|$)", args)
    return (not to_stdout), False


def check_script(script: str) -> list[str]:
    """Return messages for one unit of shell. Empty means it passes."""
    if EXEMPT.search(script):
        return []
    downloads = 0
    same_origin = 0
    problems: list[str] = []
    commands = _commands(script)
    url_vars = _url_vars(commands)
    uses_download = any(_USE.search(c) for c in commands)
    for pipeline in commands:
        is_dl, to_shell = _is_download(pipeline, url_vars)
        if to_shell:
            problems.append(f"download piped into an interpreter cannot be verified before it runs: {pipeline.strip()[:120]}")
        if _FETCHER.search(pipeline) and _has_url(pipeline, url_vars) and _CHECKSUM_FILE.search(pipeline.split("|")[0]):
            same_origin += 1
            continue
        if _FETCHER.search(pipeline) and _SIGNATURE_FILE.search(pipeline.split("|")[0]):
            continue
        piped = "|" in pipeline
        if is_dl and (piped or uses_download):
            downloads += 1
    # Count verifications over the comment-stripped text: one appearing only
    # in a comment verifies nothing. A checksum file from the same release
    # backs no verification.
    verifications = max(0, len(_VERIFY.findall("\n".join(_commands(script)))) - same_origin)
    if same_origin and downloads > verifications:
        problems.append("a checksum file downloaded beside the asset proves the download is intact, not authentic; "
                        "verify against a digest recorded in the repository or a pinned signing key")
    if downloads > verifications:
        problems.append(
            f"{downloads} download(s) but {verifications} verification(s); verify each downloaded file "
            "against a recorded SHA-256 or signing-key fingerprint before using it"
        )
    return problems


# ---------------------------------------------------------------- Dockerfiles


def _dockerfile_units(text: str) -> list[tuple[int, str, str]]:
    """Yield (line, instruction, body) for each instruction, continuations joined."""
    units: list[tuple[int, str, str]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        start = i + 1
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        body = [line]
        # A heredoc body (RUN <<EOF) runs until its terminator.
        heredoc = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", line)
        while body[-1].rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            body.append(lines[i])
        if heredoc:
            term = heredoc.group(1)
            while i + 1 < len(lines):
                i += 1
                body.append(lines[i])
                if lines[i].strip() == term:
                    break
        joined = "\n".join(body)
        instr = joined.lstrip().split(None, 1)[0].upper()
        units.append((start, instr, joined))
        i += 1
    return units


def check_dockerfile(path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for line, instr, body in _dockerfile_units(text):
        if instr == "RUN":
            script = re.sub(r"^\s*RUN\s+(?:--\S+\s+)*", "", body, count=1, flags=re.I)
            findings += [Finding(path, line, m) for m in check_script(script)]
        elif instr == "ADD":
            m = _ADD_URL.match(body)
            if m and "--checksum=sha256:" not in m.group("flags"):
                findings.append(Finding(path, line, f"ADD {m.group('src')} without --checksum=sha256:<digest>"))
    return findings


# ---------------------------------------------------------------- workflows


def _step_line(text: str, step: dict, occurrence: int = 0) -> int:
    """Best-effort line of a step: its name, else the first line of its script.

    `occurrence` picks among steps that share a name (the same install step
    repeated in two jobs), so each is reported at its own line.
    """
    name = step.get("name")
    lines = text.splitlines()
    if isinstance(name, str):
        pat = re.compile(r"^\s*-?\s*name:\s*['\"]?" + re.escape(name) + r"['\"]?\s*$")
        hits = [n for n, line in enumerate(lines, 1) if pat.match(line)]
        if hits:
            return hits[min(occurrence, len(hits) - 1)]
    script = step.get("run") or ""
    first = next((s.strip() for s in script.splitlines() if s.strip()), "")
    for n, line in enumerate(lines, 1):
        if first and first in line:
            return n
    return 1


def check_workflow(path: str, text: str) -> list[Finding]:
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return [Finding(path, 1, f"unparseable YAML: {exc}")]
    steps: list[dict] = []
    for job in (doc.get("jobs") or {}).values():
        if isinstance(job, dict):
            steps += [s for s in job.get("steps") or [] if isinstance(s, dict)]
    runs = doc.get("runs")
    if isinstance(runs, dict):
        steps += [s for s in runs.get("steps") or [] if isinstance(s, dict)]
    findings: list[Finding] = []
    seen: dict[object, int] = {}
    for step in steps:
        key = step.get("name")
        occurrence = seen.get(key, 0)
        seen[key] = occurrence + 1
        script = step.get("run")
        if not isinstance(script, str):
            continue
        for message in check_script(script):
            findings.append(Finding(path, _step_line(text, step, occurrence), f"step '{step.get('name', '?')}': {message}"))
    return findings


# ---------------------------------------------------------------- pin coherence


def parse_env(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Z0-9_]+)=(.*?)\s*$", line)
        if m:
            values[m.group(1)] = m.group(2)
    return values


def check_versions_env(path: str, text: str) -> list[Finding]:
    findings = []
    for n, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^\s*([A-Z0-9_]+_SHA256)=(.*?)\s*$", line)
        if m and not re.fullmatch(r"[0-9a-f]{64}", m.group(2)):
            findings.append(Finding(path, n, f"{m.group(1)} is not a 64-character lowercase hex SHA-256"))
    return findings


def check_arg_defaults(path: str, text: str, pins: dict[str, str]) -> list[Finding]:
    """A Dockerfile's own default for a digest must match versions.env.

    Only the defaults are checked: they are what an argument-less build (e.g.
    `docker compose build`) uses. The version it belongs to is checked with it,
    since a digest default is only meaningful beside the version default.
    """
    findings = []
    defaults = {}
    for n, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^\s*ARG\s+([A-Z0-9_]+)=(\S+)\s*$", line)
        if m:
            defaults[m.group(1)] = (n, m.group(2))
    for name, (n, value) in defaults.items():
        if not name.endswith("_SHA256") or name not in pins:
            continue
        if value != pins[name]:
            findings.append(Finding(path, n, f"ARG {name} default differs from {VERSIONS_ENV}"))
        version = name[: -len("_SHA256")] + "_VERSION"
        if version in defaults and version in pins and defaults[version][1] != pins[version]:
            findings.append(Finding(path, defaults[version][0], f"ARG {version} default differs from {VERSIONS_ENV}, so its digest default is for another version"))
    return findings


# ---------------------------------------------------------------- driver


def is_dockerfile(name: str) -> bool:
    base = pathlib.PurePosixPath(name).name
    return base == "Dockerfile" or base.endswith(".Dockerfile") or base.startswith("Dockerfile.")


def is_workflow(name: str) -> bool:
    p = pathlib.PurePosixPath(name)
    if p.name.endswith((".yml.template", ".yaml.template")):
        return True
    if p.suffix not in (".yml", ".yaml"):
        return False
    return name.startswith(".github/workflows/") or (name.startswith(".github/actions/") and p.stem == "action")


def tracked_files(root: pathlib.Path) -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True, text=True).stdout
    return [f for f in out.split("\0") if f and not f.startswith("spec-archive/")]


def scan(root: pathlib.Path, files: list[str] | None = None) -> list[Finding]:
    files = tracked_files(root) if files is None else files
    env_path = root / VERSIONS_ENV
    pins = parse_env(env_path.read_text()) if env_path.exists() else {}
    findings: list[Finding] = []
    if env_path.exists():
        findings += check_versions_env(VERSIONS_ENV, env_path.read_text())
    for name in files:
        path = root / name
        if not path.is_file():
            continue
        if is_dockerfile(name):
            text = path.read_text(errors="replace")
            findings += check_dockerfile(name, text)
            findings += check_arg_defaults(name, text, pins)
        elif is_workflow(name):
            findings += check_workflow(name, path.read_text(errors="replace"))
    return findings


def main(argv: list[str] | None = None) -> int:
    """`download-integrity [--root DIR] [FILE ...]` -- FILEs relative to the root."""
    import argparse

    ap = argparse.ArgumentParser(prog="download-integrity", description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd(), help="repository root (default: cwd)")
    ap.add_argument("files", nargs="*", help="files to check (default: every tracked file)")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    files = [f for f in args.files if is_dockerfile(f) or is_workflow(f)] if args.files else None
    findings = scan(root, files)
    for f in findings:
        print(f)
    if findings:
        print(f"\n{len(findings)} unverified download finding(s). See HHT-OPS-ci-tool-download-integrity "
          "and hooks/download-integrity/README.md.", file=sys.stderr)
        return 1
    print("download-integrity: every download is verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
