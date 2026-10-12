"""Offline tests for the reusable sponsor archive workflows.

The archives are compliance records, so the cases that matter are the ones
that would write a wrong or empty record: a run id that is not one, an
operation the caller did not state, and a sponsor read from anywhere but
sponsor.toml. Steps are extracted verbatim and run against fixtures.
"""
import os
import pathlib
import subprocess

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOGS = (ROOT / ".github/workflows/archive-deployment-logs.yml").read_text()
BUILDS = (ROOT / ".github/workflows/archive-build-artifacts.yml").read_text()


def _run_body(text: str, step_name: str) -> str:
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


VALIDATE = _run_body(LOGS, "Validate the request")
SPONSOR = _run_body(BUILDS, "Read the sponsor id")


def _validate(tmp_path, run_id, op):
    out = tmp_path / "out"
    out.write_text("")
    env = {**os.environ, "RUN_ID": run_id, "OPERATION_TYPE": op, "GITHUB_OUTPUT": str(out)}
    return subprocess.run(["bash", "-c", VALIDATE], env=env, capture_output=True, text=True)


@pytest.mark.parametrize("op", ["deploy", "hotfix-deploy", "manual"])
def test_stated_operation_is_accepted(tmp_path, op):
    r = _validate(tmp_path, "123", op)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("op", ["", "unknown", "Portal"])
def test_unstated_operation_is_refused(tmp_path, op):
    r = _validate(tmp_path, "123", op)
    assert r.returncode != 0
    assert "operation_type" in r.stdout


@pytest.mark.parametrize("run_id", ["", "12a", "../1"])
def test_non_numeric_run_id_is_refused(tmp_path, run_id):
    r = _validate(tmp_path, run_id, "deploy")
    assert r.returncode != 0
    assert "numeric run id" in r.stdout


BUILDS_VALIDATE = _run_body(BUILDS, "Validate the request")


def _validate_builds(reports_run_id, deploy_run_id=""):
    env = {**os.environ, "REPORTS_RUN_ID": reports_run_id, "DEPLOY_RUN_ID": deploy_run_id}
    return subprocess.run(["bash", "-c", BUILDS_VALIDATE], env=env, capture_output=True, text=True)


@pytest.mark.parametrize("deploy_run_id", ["", "456"])
def test_build_archive_numeric_run_ids_are_accepted(deploy_run_id):
    r = _validate_builds("123", deploy_run_id)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("run_id", ["", "12a", "../1"])
def test_build_archive_non_numeric_reports_run_id_is_refused(run_id):
    """A bad id would only miss the download, which is tolerated, and archive nothing."""
    r = _validate_builds(run_id)
    assert r.returncode != 0
    assert "reports_run_id must be a numeric run id" in r.stdout


def test_build_archive_non_numeric_deploy_run_id_is_refused():
    r = _validate_builds("123", "../1")
    assert r.returncode != 0
    assert "deploy_run_id" in r.stdout


# Verifies: HHT-OPS-sponsor-name-is-data/B
def test_archive_sponsor_is_read_from_sponsor_toml(tmp_path):
    (tmp_path / "sponsor.toml").write_text('schema = 1\nid = "example"\n')
    out = tmp_path / "out"
    out.write_text("")
    env = {**os.environ, "GITHUB_OUTPUT": str(out)}
    r = subprocess.run(["bash", "-c", SPONSOR], env=env, cwd=tmp_path,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "sponsor=example" in out.read_text()


def test_archive_without_sponsor_toml_is_refused(tmp_path):
    out = tmp_path / "out"
    out.write_text("")
    env = {**os.environ, "GITHUB_OUTPUT": str(out)}
    r = subprocess.run(["bash", "-c", SPONSOR], env=env, cwd=tmp_path,
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert "sponsor.toml" in r.stdout


@pytest.mark.parametrize("text", [LOGS, BUILDS])
def test_archives_are_called_only(text):
    doc = yaml.safe_load(text)
    on = doc[True] if True in doc else doc["on"]
    assert set(on) == {"workflow_call"}


@pytest.mark.parametrize("text", [LOGS, BUILDS])
def test_upload_is_verified_against_the_packaged_checksum(text):
    assert 'if [ "$want" != "$got" ]' in text
