"""Offline unit tests for the cloud-run-resolve-serving-digest action's resolve script.

Covers the decisions that make a promotion mean anything: that the digest comes
from the revision actually serving traffic rather than the newest one, and that
split traffic, an idle service, a partial rollout, a mutable tag and a malformed
reference each refuse instead of guessing.

The readiness job (``.github/workflows/readiness-checks.yml``) can only observe
the composite's *outcome* against a live project, and it cannot produce these
states on demand — you cannot readily ask a real service to split its traffic
just to watch a refusal. These tests close that gap: they extract the resolve
step straight out of ``action.yml`` — so the test cannot drift from the action —
and run it against a stub ``gcloud`` fed recorded API responses, asserting both
the exit code AND the specific ``::error::`` message for each path.

Verifies: DIARY-OPS-promotion-digest-resolution/A+C+D — that the promoted artifact
is read from the source environment's serving revision, that a source with no
single serving revision is refused rather than guessed at, and that a reference
failing the digest-pinned shape check never reaches a later command.
"""
import os
import subprocess
from pathlib import Path

import pytest

ACTION = Path(__file__).resolve().parents[1] / "action.yml"
FIXTURES = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "resolve-serving-digest"

DIGEST_A = "sha256:aaaa" + "1" * 60
DIGEST_B = "sha256:bbbb" + "2" * 60


def _extract_resolve_script(text: str) -> str:
    """Return the body of the resolve step's `run: |` block, verbatim."""
    out, in_step, grabbing = [], False, False
    for ln in text.splitlines():
        if ln.startswith("    - name: Resolve the digest currently serving all traffic"):
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
    assert script, "could not extract the resolve run: block from action.yml"
    return script


RESOLVE = _extract_resolve_script(ACTION.read_text())

# Stub gcloud: dispatch on the subcommand, print the fixture for this scenario.
# `revisions describe` uses --format='value(...)' so it emits a bare string,
# matching what the real CLI hands back.
_STUB = """#!/usr/bin/env bash
case "$1 $2" in
  "run services")  cat "$FIXTURE_DIR/service.json" ;;
  "run revisions") python3 -c 'import json,os,sys; print(json.load(open(os.environ["FIXTURE_DIR"]+"/revision.json"))["spec"]["containers"][0]["image"])' ;;
  *) echo "unexpected gcloud invocation: $*" >&2; exit 64 ;;
esac
"""


def _run(scenario, tmp_path):
    """Execute the extracted step against a fixture; return (proc, outputs dict)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "gcloud"
    stub.write_text(_STUB)
    stub.chmod(0o755)

    outputs = tmp_path / "gh_output"
    outputs.write_text("")

    env = dict(os.environ)
    env.update(
        PATH=f"{bin_dir}:{env['PATH']}",
        FIXTURE_DIR=str(FIXTURES / scenario),
        GITHUB_OUTPUT=str(outputs),
        SERVICE="portal-service",
        REGION="europe-west1",
        PROJECT="example-dev",
    )
    proc = subprocess.run(
        ["bash", "-c", RESOLVE], env=env, capture_output=True, text=True
    )
    parsed = dict(
        line.split("=", 1) for line in outputs.read_text().splitlines() if "=" in line
    )
    return proc, parsed


def test_single_serving_revision_resolves_its_digest(tmp_path):
    proc, out = _run("single-serving", tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert out["image_digest"].endswith("@" + DIGEST_A)
    assert out["revision_name"] == "portal-service-00042-abc"


def test_newest_revision_is_ignored_when_it_serves_no_traffic(tmp_path):
    """The deploy path publishes at zero traffic and migrates afterwards, so a
    failed deploy leaves a newer revision that was never live. Reading "latest"
    would promote bytes this environment never ran."""
    proc, out = _run("newer-not-serving", tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert out["revision_name"] == "portal-service-00042-abc"   # the older, serving one
    assert out["image_digest"].endswith("@" + DIGEST_A)
    assert DIGEST_B not in out["image_digest"]


def test_split_traffic_refuses_rather_than_choosing(tmp_path):
    proc, out = _run("split-traffic", tmp_path)
    assert proc.returncode != 0
    assert "split across 2 revisions" in proc.stdout
    assert out == {}


def test_no_revision_serving_refuses(tmp_path):
    proc, out = _run("nothing-serving", tmp_path)
    assert proc.returncode != 0
    assert "is receiving traffic" in proc.stdout
    assert out == {}


def test_mutable_tag_reference_is_rejected(tmp_path):
    proc, out = _run("tag-not-digest", tmp_path)
    assert proc.returncode != 0
    assert "not pinned to an immutable content digest" in proc.stdout
    assert out == {}


def test_reference_with_a_trailing_shell_fragment_is_rejected(tmp_path):
    """The reference is server-supplied and flows into later command text, so a
    digest with a shell fragment appended must fail the anchored shape check
    rather than pass as a 'valid enough' prefix."""
    proc, out = _run("malformed-ref", tmp_path)
    assert proc.returncode != 0
    assert "not pinned to an immutable content digest" in proc.stdout
    assert out == {}
    assert not Path("/tmp/pwned").exists()


def test_partial_rollout_is_not_treated_as_proved(tmp_path):
    """A lone revision holding less than all traffic is a rollout in progress,
    not a state this environment can be said to have proved."""
    scenario = tmp_path / "partial"
    scenario.mkdir()
    (scenario / "service.json").write_text(
        '{"status":{"traffic":[{"revisionName":"portal-service-00042-abc","percent":50}]}}'
    )
    (scenario / "revision.json").write_text(
        '{"spec":{"containers":[{"image":"example.dev/x@' + DIGEST_A + '"}]}}'
    )
    bin_dir = tmp_path / "bin2"
    bin_dir.mkdir()
    stub = bin_dir / "gcloud"
    stub.write_text(_STUB)
    stub.chmod(0o755)
    outputs = tmp_path / "gh_output2"
    outputs.write_text("")
    env = dict(os.environ)
    env.update(
        PATH=f"{bin_dir}:{env['PATH']}",
        FIXTURE_DIR=str(scenario),
        GITHUB_OUTPUT=str(outputs),
        SERVICE="portal-service",
        REGION="europe-west1",
        PROJECT="example-dev",
    )
    proc = subprocess.run(["bash", "-c", RESOLVE], env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "50%, not 100%" in proc.stdout
    assert outputs.read_text() == ""
