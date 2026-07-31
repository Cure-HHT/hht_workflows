"""Offline unit tests for the cosign-verify composite action's verify script.

Covers the action's default soft-fail branch and its digest-pinning, empty-list,
and non-integer-retry config guards.

The end-to-end readiness job (``.github/workflows/readiness-checks.yml``) can only
observe the composite's *outcome* (a composite has no outputs and its log is not
readable downstream). These unit tests close that gap: they extract the
"Verify signatures" bash step straight out of ``action.yml`` — so the test cannot
drift from the action — and run it against a stub ``cosign``, asserting both the
exit code AND the specific ``::error::`` / ``::warning::`` message for each path:
the default soft-fail branch, the digest-pinning (F2), empty-list (F4) and
non-integer-retry (F3) guards, and multi-image list handling.

Each test fails if that behaviour regresses and passes against the action as it
stands today (it changes nothing about the action).
"""
import os
import subprocess
from pathlib import Path

ACTION = Path(__file__).resolve().parents[1] / "action.yml"

GOOD = "ghcr.io/cure-hht/x@sha256:" + "a" * 64
BAD = "ghcr.io/cure-hht/x@sha256:" + "b" * 64   # stub cosign fails digests of all-b
TAG = "ghcr.io/cure-hht/x:latest"               # not digest-pinned -> F2


def _extract_verify_script(text: str) -> str:
    """Return the body of the 'Verify signatures' `run: |` block, verbatim."""
    lines = text.splitlines()
    out, in_step, grabbing = [], False, False
    for ln in lines:
        if ln.startswith("    - name: Verify signatures"):
            in_step = True
            continue
        if in_step and not grabbing and ln.strip() == "run: |":
            grabbing = True
            continue
        if grabbing:
            if ln.startswith("        "):        # 8-space block-scalar body
                out.append(ln[8:])
            elif ln.strip() == "":
                out.append("")
            else:
                break
    script = "\n".join(out).strip("\n")
    assert script, "could not extract the Verify signatures run: block from action.yml"
    return script


VERIFY = _extract_verify_script(ACTION.read_text())

# Stub cosign: fail verification for any digest of all-'b', succeed otherwise.
# Lets a single multi-image invocation contain both a passing and a failing ref.
_STUB = (
    "#!/usr/bin/env bash\n"
    'for a in "$@"; do case "$a" in *sha256:bbb*) exit 1 ;; esac; done\n'
    "exit 0\n"
)


def run(tmp_path, images, *, retries="1", soft_fail="true"):
    """Run the extracted verify script with a stub cosign; return (rc, log, summary)."""
    binp = tmp_path / "bin"
    binp.mkdir(exist_ok=True)
    (binp / "cosign").write_text(_STUB)
    (binp / "cosign").chmod(0o755)
    summary = tmp_path / "summary.md"
    env = {
        **os.environ,
        "PATH": f"{binp}:{os.environ['PATH']}",
        "IMAGES": images,
        "IDENTITY_REGEXP": "irrelevant-to-stub",
        "OIDC_ISSUER": "irrelevant-to-stub",
        "RETRIES": retries,
        "SOFT_FAIL": soft_fail,
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    p = subprocess.run(["bash", "-c", VERIFY], env=env, capture_output=True, text=True)
    log = p.stdout + p.stderr
    return p.returncode, log, (summary.read_text() if summary.exists() else "")


def test_default_soft_fail_warns_and_passes(tmp_path):
    # soft-fail left at its default ('true'): a failed verification warns, exit 0.
    rc, log, _ = run(tmp_path, BAD, soft_fail="true")
    assert rc == 0, log
    assert "::warning::cosign verification failed" in log
    assert "soft-fail" in log


def test_soft_fail_false_fails_hard(tmp_path):
    rc, log, _ = run(tmp_path, BAD, soft_fail="false")
    assert rc == 1, log
    assert "::error::cosign verification failed" in log


def test_digest_pinning_rejects_tag_even_under_soft_fail(tmp_path):
    # F2: a tag ref is rejected and fails the job regardless of soft-fail: 'true'.
    rc, log, _ = run(tmp_path, TAG, soft_fail="true")
    assert rc == 1, log
    assert "must be pinned by digest" in log
    assert "failing regardless of soft-fail" in log


def test_empty_image_list_is_config_error(tmp_path):
    # F4: no non-empty refs -> config error, exit 1.
    rc, log, _ = run(tmp_path, "", soft_fail="true")
    assert rc == 1, log
    assert "no non-empty image references" in log


def test_non_integer_retries_is_config_error(tmp_path):
    # F3: retries must be a non-negative integer.
    rc, log, _ = run(tmp_path, GOOD, retries="abc")
    assert rc == 1, log
    assert "retries must be a non-negative integer" in log


def test_multi_image_one_bad_fails(tmp_path):
    # The loop verifies every ref; one failing ref fails the batch (soft-fail off).
    rc, _, summary = run(tmp_path, f"{GOOD}\n{BAD}", soft_fail="false")
    assert rc == 1
    assert "verified" in summary         # the good ref
    assert "VERIFY FAILED" in summary    # the bad ref


def test_multi_image_all_good_passes(tmp_path):
    rc, _, summary = run(tmp_path, f"{GOOD}\n{GOOD}", soft_fail="false")
    assert rc == 0
    assert summary.count("verified") == 2
