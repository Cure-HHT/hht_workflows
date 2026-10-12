"""Offline tests for the reusable sponsor database reset.

A reset is destructive and irreversible, so its refusals are the safety
behaviour: production is refused by name, the operator must type the target
again, and the environment's variables must agree with sponsor.toml before the
job image reaches a project. Each step is extracted verbatim from reset-db.yml
and driven against fixtures.
"""
import os
import pathlib
import subprocess

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/reset-db.yml"
TEXT = WORKFLOW.read_text()
DOC = yaml.safe_load(TEXT)


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


GUARD = _run_body(TEXT, "Refuse production and require the typed confirmation")
IDENTITY = _run_body(TEXT, "Read the sponsor identity")
CROSS_CHECK = _run_body(TEXT, "Confirm the environment matches the sponsor identity")

SPONSOR_TOML = """\
schema = 1
id = "example"
display_name = "Example Study"
repository = "hht_diary_example"
req_namespace = "EXA"
linking_code_prefix = "EX"
doppler_project = "example-runtime"
artifact_registry_repository = "example-images"

[environments.dev]
gcp_project_id = "example-proj-dev"

[environments.prod]
gcp_project_id = "example-proj-prod"
"""

BASE_CONFIG = """\
{
  "gar": {"host": "region9-docker.pkg.dev", "project": "platform-artifacts"},
  "gcp": {
    "project_number": "123456789012",
    "actions_sa_email": "actions@platform-artifacts.iam.gserviceaccount.com"
  }
}
"""


def _guard(target, confirm):
    env = {**os.environ, "TARGET_ENV": target, "CONFIRM": confirm}
    return subprocess.run(["bash", "-c", GUARD], env=env, capture_output=True, text=True)


@pytest.mark.parametrize("target", ["prod", "PROD", "example-prod", "Prod"])
def test_production_is_refused(target):
    r = _guard(target, target)
    assert r.returncode != 0
    assert "Production resets are forbidden" in r.stdout


def test_mismatched_confirmation_is_refused():
    r = _guard("dev", "qa")
    assert r.returncode != 0
    assert "does not match target environment 'dev'" in r.stdout


def test_matching_confirmation_proceeds():
    r = _guard("dev", "dev")
    assert r.returncode == 0, r.stdout + r.stderr


def _identity(tmp_path, toml=SPONSOR_TOML, **overrides):
    (tmp_path / "deployment").mkdir(exist_ok=True)
    if toml is not None:
        (tmp_path / "sponsor.toml").write_text(toml)
    (tmp_path / "deployment/base-config.json").write_text(BASE_CONFIG)
    out = tmp_path / "github_output"
    out.write_text("")
    env = {
        **os.environ,
        "TARGET_ENV": "dev",
        "GITHUB_REPOSITORY": "Example-Org/hht_diary_example",
        "GITHUB_SHA": "e" * 40,
        "GITHUB_OUTPUT": str(out),
        **overrides,
    }
    proc = subprocess.run(["bash", "-c", IDENTITY], env=env, cwd=tmp_path,
                          capture_output=True, text=True)
    proc.outputs = dict(  # type: ignore[attr-defined]
        ln.split("=", 1) for ln in out.read_text().splitlines() if "=" in ln
    )
    return proc


# Verifies: HHT-OPS-sponsor-name-is-data/B
def test_reset_identity_is_read_from_sponsor_toml(tmp_path):
    r = _identity(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.outputs["sponsor_id"] == "example"
    assert r.outputs["doppler_project"] == "example-runtime"
    assert r.outputs["declared_project"] == "example-proj-dev"
    assert r.outputs["job_image"] == (
        "region9-docker.pkg.dev/platform-artifacts/example-images/db-reset-job:" + "e" * 12
    )
    assert r.outputs["registry_host"] == "region9-docker.pkg.dev"


def test_undeclared_environment_is_refused(tmp_path):
    r = _identity(tmp_path, TARGET_ENV="qa")
    assert r.returncode != 0
    assert "'qa' is not declared" in r.stdout


def test_identity_of_another_repository_is_refused(tmp_path):
    r = _identity(tmp_path, GITHUB_REPOSITORY="Example-Org/other")
    assert r.returncode != 0
    assert "declares repository 'hht_diary_example'" in r.stdout


def _cross(**overrides):
    env = {
        **os.environ,
        "TARGET_ENV": "dev",
        "DECLARED_PROJECT": "example-proj-dev",
        "GCP_PROJECT_ID": "example-proj-dev",
        "GCP_REGION": "region9",
        "VPC_CONNECTOR": "example-dev-vpc-con",
        "DOPPLER_RUNTIME_IDENTITY_ID": "00000000-0000-0000-0000-000000000001",
        "DOPPLER_RUNTIME_AUDIENCE": "doppler-runtime:example:dev",
        **overrides,
    }
    return subprocess.run(["bash", "-c", CROSS_CHECK], env=env, capture_output=True, text=True)


def test_consistent_environment_passes():
    r = _cross()
    assert r.returncode == 0, r.stdout + r.stderr


def test_environment_naming_another_project_is_refused():
    r = _cross(GCP_PROJECT_ID="example-proj-uat")
    assert r.returncode != 0
    assert "sponsor.toml declares 'example-proj-dev'" in r.stdout


@pytest.mark.parametrize(
    "name",
    ["GCP_PROJECT_ID", "GCP_REGION", "VPC_CONNECTOR",
     "DOPPLER_RUNTIME_IDENTITY_ID", "DOPPLER_RUNTIME_AUDIENCE"],
)
def test_missing_environment_variable_is_refused(name):
    r = _cross(**{name: ""})
    assert r.returncode != 0
    assert name in r.stdout


def test_guards_run_before_the_environment_approval():
    """A refused reset must not first ask a reviewer to approve it."""
    resolve = DOC["jobs"]["resolve"]
    assert "environment" not in resolve
    names = [s.get("name") for s in resolve["steps"]]
    assert "Refuse production and require the typed confirmation" in names
    assert DOC["jobs"]["reset"]["needs"] == "resolve"
    assert "inputs.target-env" in DOC["jobs"]["reset"]["environment"]


def test_no_stored_doppler_token_is_read():
    assert "secrets.DOPPLER_TOKEN" not in TEXT
