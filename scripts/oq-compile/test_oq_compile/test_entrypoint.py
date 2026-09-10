"""Regression coverage for oq-compile.sh, the shell entrypoint.

commit e0bc2f9 fixed a bug where the final invocation line passed
"${ASSOC_ARGS[@]:-}" — under `set -u`, bash expands an EMPTY array with
that form to a single empty-string WORD rather than to nothing, so a
single-repo run with no associate root sent compile-oq.py a stray ""
positional argument. compile-oq.py declares no positionals, so argparse
exited 2 with "unrecognized arguments" on every no-associate run. This
module drives the real oq-compile.sh as a subprocess, with only the
upstream `elspais` CLI replaced by a stub (running the real CLI against
real repos is out of scope here — Task 8's job), so the bug class is
guarded by a committed test instead of a discarded manual harness.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

TOOL_DIR = Path(__file__).resolve().parents[1]
ENTRYPOINT = TOOL_DIR / "oq-compile.sh"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="oq-compile.sh entrypoint test requires bash and git on PATH",
)

# A stub `elspais` answering only the four subcommands oq-compile.sh calls:
# --version, associate, trace, graph. `trace` and `graph` copy the existing
# load.py/pivot.py test fixtures to whatever -o path they were given, so the
# real compile-oq.py runs unstubbed against real (fixture) JSON.
_STUB_ELSPAIS = """#!/usr/bin/env bash
set -euo pipefail
FIXTURES="{fixtures}"
# Record every invocation's argv so a test can assert the CLI contract the
# entrypoint depends on, which is otherwise invisible: the stub answers the
# same whatever flags it is handed.
if [ -n "${{ELSPAIS_ARGV_LOG:-}}" ]; then
  printf '%s\\n' "$*" >> "$ELSPAIS_ARGV_LOG"
fi
_out_arg() {{
  local prev=""
  for a in "$@"; do
    if [ "$prev" = "-o" ]; then printf '%s' "$a"; return; fi
    prev="$a"
  done
}}
case "$1" in
  --version)
    echo "elspais 0.999.0 (test stub)"
    ;;
  associate)
    ;;
  trace)
    cp "$FIXTURES/sample-trace.json" "$(_out_arg "$@")"
    ;;
  graph)
    cp "$FIXTURES/sample-graph.json" "$(_out_arg "$@")"
    ;;
  *)
    echo "stub elspais: unhandled subcommand $1" >&2
    exit 1
    ;;
esac
"""


def _git_init_with_commit(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=test",
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "init",
        ],
        cwd=path,
        check=True,
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _make_stub_elspais(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "elspais"
    stub.write_text(_STUB_ELSPAIS.format(fixtures=FIXTURES))
    stub.chmod(0o755)


def _make_primary(root: Path) -> None:
    manifest_dir = root / "spec" / "OQ-manifest"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "oq.yaml").write_text(
        (FIXTURES / "sample-manifest.yaml").read_text()
    )
    _git_init_with_commit(root)


def _run_entrypoint(
    tmp_path: Path, primary: Path, *extra_args: str, argv_log: Path | None = None
) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    _make_stub_elspais(bin_dir)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    if argv_log is not None:
        env["ELSPAIS_ARGV_LOG"] = str(argv_log)
    return subprocess.run(
        ["bash", str(ENTRYPOINT), str(primary), *extra_args],
        env=env,
        capture_output=True,
        text=True,
    )


def test_no_associate_root_exits_zero_and_writes_deliverables(tmp_path):
    """The path that was broken: no associate root at all."""
    primary = tmp_path / "primary"
    _make_primary(primary)

    result = _run_entrypoint(tmp_path, primary)

    assert result.returncode == 0, (
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert (primary / "promotion-evidence" / "_reports" / "oq-req.csv").exists()
    assert (primary / "promotion-evidence" / "_reports" / "oq-uat.csv").exists()
    assert (primary / "promotion-evidence" / "_build" / "oq-report.xlsx").exists()


def test_with_associate_root_reaches_provenance(tmp_path):
    """The path that already worked: confirms the fix did not regress it,
    and that the associate's commit is threaded all the way into the
    workbook's Provenance sheet."""
    import openpyxl

    primary = tmp_path / "primary"
    _make_primary(primary)
    associate = tmp_path / "associate"
    associate_sha = _git_init_with_commit(associate)

    result = _run_entrypoint(tmp_path, primary, str(associate))

    assert result.returncode == 0, (
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    wb = openpyxl.load_workbook(
        primary / "promotion-evidence" / "_build" / "oq-report.xlsx"
    )
    prov_rows = list(wb["Provenance"].iter_rows(values_only=True))
    matches = [row for row in prov_rows if row[0] == "Associate repository commit"]
    assert matches, "no 'Associate repository commit' row in the Provenance sheet"
    assert matches[0][1] == f"associate@{associate_sha}"


def test_trace_asks_for_the_verification_values_and_not_the_uat_dimension(tmp_path):
    """The requirement sheet reports test-verification evidence beside the
    user-acceptance verdict. `--dimension uat` suppresses the `verified` and
    `tested` figures that evidence is computed from, so the entrypoint must
    name the values instead. Nothing else in the suite sees the flags the
    entrypoint sends -- the loader is fed fixtures -- so a silent reversion
    here would render a report whose test column is uniformly wrong."""
    primary = tmp_path / "primary"
    _make_primary(primary)
    argv_log = tmp_path / "elspais-argv.log"

    result = _run_entrypoint(tmp_path, primary, argv_log=argv_log)
    assert result.returncode == 0, (
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    trace_calls = [
        line for line in argv_log.read_text().splitlines() if line.startswith("trace ")
    ]
    assert len(trace_calls) == 1, argv_log.read_text()
    call = trace_calls[0]
    assert "--dimension" not in call
    assert (
        "--values id,title,level,status,verified,tested,uat_verified,journeys" in call
    )
