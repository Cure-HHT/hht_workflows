"""Offline tests for the promote-template source-health gate.

Verifies: HSI-OPS-promotion-gate-qa/D — the source deployment is confirmed
healthy before a promotion proceeds.
Verifies: DIARY-OPS-artifact-source-attestation/B+C — the source revisions the
promotion advances are read FROM the artifact, and a promotion refuses when the
artifact cannot state one.

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
REVISIONS = _run_body(
    WORKFLOW.read_text(), "Read the source revisions the artifact reports"
)


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

        # The step hands its fetched health body to the next step through
        # $GITHUB_ENV rather than re-fetching it, so the harness has to model
        # that file: the body runs under `set -u`, and an unset GITHUB_ENV
        # would kill it before any assertion about the gate could be made.
        github_env = tmp_path / "github_env"
        github_env.touch()

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
            "GITHUB_ENV": str(github_env),
        }
        proc = subprocess.run(
            ["bash", "-c", SCRIPT], env=env, capture_output=True, text=True
        )
        proc.github_env = github_env.read_text()  # type: ignore[attr-defined]
        return proc

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


# --- Source-revision attestation (DIARY-OPS-artifact-source-attestation/B+C) --

# The health step above establishes that the source environment is well; this
# one establishes WHAT it is running. The distinction matters because the
# promotion's next act is to look a validation result up, and a result found
# under an identifier the operator supplied verifies the operator's belief
# rather than the deployment.


def revisions(health, **overrides):
    """Run the revision-read body against a health manifest, as env."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "github_output"
        out.touch()
        env = {
            **os.environ,
            "HEALTH_BODY": health,
            "SOURCE_ENV": "dev",
            "GITHUB_OUTPUT": str(out),
            **overrides,
        }
        proc = subprocess.run(
            ["bash", "-c", REVISIONS], env=env, capture_output=True, text=True
        )
        proc.output = out.read_text()  # type: ignore[attr-defined]
        return proc


def test_reads_both_revisions_the_artifact_reports():
    """The one the first draft of this design got wrong. A portal-final image
    composes two independently pinned core images: `server_commit` is written
    only when the version-gated portal-server binary is rebuilt, while
    `core_commit` advances with the sponsor-ci tree the portal UI is compiled
    from. Reading one and calling it "the" source revision would let a later
    lookup find a passing record about code the artifact does not contain."""
    r = revisions(
        '{"status":"ok","versions":{"server_commit":"b3f21aa",'
        '"core_commit":"9e4c17dabc1234567890abcdef1234567890abcd"}}'
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.output.strip() == (
        "source_revisions=b3f21aa 9e4c17dabc1234567890abcdef1234567890abcd"
    ), r.output


def test_collapses_the_pair_when_both_halves_share_a_revision():
    """A build where the binary and the UI came from one commit reports it
    twice. The gate downstream would refuse a duplicate lookup for no reason,
    so the pair is deduplicated here rather than there."""
    r = revisions(
        '{"status":"ok","versions":{"server_commit":"b3f21aa","core_commit":"b3f21aa"}}'
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.output.strip() == "source_revisions=b3f21aa", r.output


def test_absent_core_commit_refuses():
    """C: an image built before the attestation cannot say what it is. Reading
    the one key it does carry and proceeding is how a gate ends up checking the
    wrong half of the artifact."""
    r = revisions('{"status":"ok","versions":{"server_commit":"b3f21aa"}}')
    assert r.returncode != 0, "an artifact that cannot state a revision must be refused"
    assert "reports no 'core_commit'" in r.stdout


def test_absent_server_commit_refuses():
    r = revisions('{"status":"ok","versions":{"core_commit":"9e4c17d"}}')
    assert r.returncode != 0
    assert "reports no 'server_commit'" in r.stdout


def test_manifest_without_versions_refuses():
    r = revisions('{"status":"ok"}')
    assert r.returncode != 0, "a manifest with no versions block must fail closed"
    assert "so its source revision cannot be established" in r.stdout or \
           "source revision of the artifact cannot be established" in r.stdout


def test_malformed_revision_refuses_under_its_own_reason():
    """Absent and malformed are different situations: one is fixed by
    rebuilding the image, the other means something answered but not with a
    revision. Reporting them the same way sends the operator to the wrong
    place."""
    r = revisions(
        '{"status":"ok","versions":{"server_commit":"not-a-sha","core_commit":"9e4c17d"}}'
    )
    assert r.returncode != 0
    assert "not a well-formed revision identifier" in r.stdout


def test_revision_carrying_a_trailing_shell_fragment_refuses():
    """The regex is anchored at BOTH ends. This value was read back from a live
    service and then flows into an object path and command text, so a
    valid-looking prefix must not carry a payload past the check."""
    for bad in ('b3f21aa"; curl evil.example.com #', "b3f21aa\n9999999", "../../etc"):
        r = revisions(
            '{"status":"ok","versions":{"server_commit":%s,"core_commit":"9e4c17d"}}'
            % __import__("json").dumps(bad)
        )
        assert r.returncode != 0, f"must refuse {bad!r}"


def test_uppercase_revision_refuses():
    """Git emits lowercase hex. An uppercase value did not come from the build,
    and admitting it would make two spellings of one revision look like two
    revisions to the lookup."""
    r = revisions(
        '{"status":"ok","versions":{"server_commit":"B3F21AA","core_commit":"9e4c17d"}}'
    )
    assert r.returncode != 0
    assert "not a well-formed revision identifier" in r.stdout


def test_unparseable_health_body_refuses():
    r = revisions("<html>502 Bad Gateway</html>")
    assert r.returncode != 0, "a non-JSON manifest must fail closed"
