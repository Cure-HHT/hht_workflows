"""Offline tests for the promote-template source-health gate.

Verifies: HSI-OPS-promotion-gate-qa/D — the source deployment is confirmed
healthy before a promotion proceeds.

The gate exists because a promotion advances what a source environment is said
to have *proved*. An environment that is failing has proved nothing, so
promoting out of it carries a fault forward wearing the appearance of evidence.

These states cannot be produced against a live project on demand: you cannot ask
a healthy service to start reporting `degraded` just to watch a refusal, and the
modes that matter most — unreachable, malformed body, no service URL — are
exactly the ones a working environment never offers.

So the step's `run:` body is extracted verbatim out of promote-template.yml —
the test cannot drift from the workflow — and driven against a stub `gcloud` and
a stub `curl`. Both the exit code AND the specific `::error::` text are asserted,
because an operator reading a refusal needs to know which situation they are in.
"""
import os
import pathlib
import subprocess

import pytest

WORKFLOW = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".github/workflows/promote-template.yml"
)
STEP = "Confirm ${{ inputs.source-env }} is healthy"


def _run_body(text: str, step_name: str) -> str:
    """Return the named step's `run: |` block, verbatim and de-indented."""
    out: list[str] = []
    in_step = False
    body_indent = None
    for ln in text.splitlines():
        if ln.strip() == f"- name: {step_name}":
            in_step = True
            continue
        if in_step and body_indent is None:
            if ln.strip() == "run: |":
                body_indent = (len(ln) - len(ln.lstrip())) + 2
            continue
        if body_indent is not None:
            if ln.strip() == "":
                out.append("")
            elif len(ln) - len(ln.lstrip()) >= body_indent:
                out.append(ln[body_indent:])
            else:
                break
    script = "\n".join(out).strip("\n")
    assert script, f"could not extract the run: block for {step_name!r}"
    return script


SCRIPT = _run_body(WORKFLOW.read_text(), STEP)


@pytest.fixture()
def invoke(tmp_path):
    """Run the extracted script with stubbed gcloud/curl on PATH."""

    def _invoke(url="https://portal-qa.example.run.app",
                health='{"status":"ok"}',
                curl_fails=False):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)

        # `gcloud run services describe` emits the URL; `auth
        # print-identity-token` emits a token. Anything else is a test bug, so
        # it fails loudly rather than silently returning empty.
        (bin_dir / "gcloud").write_text(
            "#!/usr/bin/env bash\n"
            'if [ "$1" = "run" ]; then printf "%s" "$STUB_URL"; exit 0; fi\n'
            'if [ "$1" = "auth" ]; then echo "stub-id-token"; exit 0; fi\n'
            'echo "unexpected gcloud invocation: $*" >&2; exit 99\n'
        )
        # Real `curl -f` exits non-zero on an HTTP error, and the step relies on
        # that to fall through to its UNREACHABLE default. The stub models it.
        (bin_dir / "curl").write_text(
            "#!/usr/bin/env bash\n"
            'if [ "$STUB_CURL_FAILS" = "1" ]; then exit 22; fi\n'
            'printf "%s" "$STUB_HEALTH"\n'
        )
        for f in ("gcloud", "curl"):
            (bin_dir / f).chmod(0o755)

        env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "STUB_URL": url,
            "STUB_HEALTH": health,
            "STUB_CURL_FAILS": "1" if curl_fails else "0",
            "SOURCE_ENV": "dev",
            "SERVICE": "portal-service",
            "REGION": "europe-west9",
            "PROJECT": "sponsor-dev",
            "SA_EMAIL": "github-actions-sa@example.iam.gserviceaccount.com",
        }
        return subprocess.run(
            ["bash", "-c", SCRIPT], env=env, capture_output=True, text=True
        )

    return _invoke


def test_healthy_source_promotes(invoke):
    r = invoke(health='{"status":"ok","service":"portal"}')
    assert r.returncode == 0, r.stderr
    assert "is healthy (status=ok)" in r.stdout


def test_degraded_source_refuses(invoke):
    r = invoke(health='{"status":"degraded"}')
    assert r.returncode != 0
    assert "status='degraded'" in r.stdout


def test_unreachable_source_refuses(invoke):
    """`curl -f` fails, so the step's own UNREACHABLE default must apply
    rather than the failure passing silently."""
    r = invoke(curl_fails=True)
    assert r.returncode != 0
    assert "status='UNREACHABLE'" in r.stdout


def test_missing_service_url_refuses(invoke):
    """Health is unknowable without a URL, and unknowable must not read as
    healthy."""
    r = invoke(url="")
    assert r.returncode != 0
    assert "Cannot read a service URL" in r.stdout


def test_malformed_health_body_refuses_with_a_named_reason(invoke):
    """A proxy answering with an HTML error page must refuse under this step's
    own diagnostic. Letting jq's parse error surface still fails closed, but
    hands the operator a message about JSON syntax when what actually happened
    is that the source environment is not serving its health endpoint."""
    r = invoke(health="<html>502 Bad Gateway</html>")
    assert r.returncode != 0
    assert "::error::" in r.stdout
    assert "unparseable" in r.stdout


def test_health_body_without_status_refuses(invoke):
    """`.status // "unknown"` must land on unknown, not on a vacuous pass."""
    r = invoke(health='{"service":"portal"}')
    assert r.returncode != 0
    assert "status='unknown'" in r.stdout
