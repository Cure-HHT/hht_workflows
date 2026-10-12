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
RUNTIME_IDENTITY = _run_body(TEXT, "Confirm the environment names its runtime identity")
LOCATE = _run_body(TEXT, "Locate the environment's VPC connector")

SPONSOR_TOML = """\
schema = 1
id = "example"
display_name = "Example Study"
repository = "hht_diary_example"
req_namespace = "EXA"
linking_code_prefix = "EX"
doppler_project = "example-runtime"
artifact_registry_repository = "example-images"
region = "europe-west9"

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
    assert r.outputs["region"] == "europe-west9"
    assert r.outputs["doppler_audience"] == "doppler-runtime:example-runtime:dev"
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


def test_missing_region_is_refused(tmp_path):
    r = _identity(tmp_path, toml=SPONSOR_TOML.replace('region = "europe-west9"\n', ""))
    assert r.returncode != 0
    assert "region must be a non-empty string" in r.stdout


# Verifies: HHT-OPS-identity-over-keys/F
def test_environment_without_a_runtime_identity_is_refused():
    env = {**os.environ, "TARGET_ENV": "dev", "DOPPLER_RUNTIME_IDENTITY_ID": ""}
    r = subprocess.run(["bash", "-c", RUNTIME_IDENTITY], env=env, capture_output=True, text=True)
    assert r.returncode != 0
    assert "DOPPLER_RUNTIME_IDENTITY_ID" in r.stdout


def _locate(tmp_path, connector_found):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gcloud = bin_dir / "gcloud"
    gcloud.write_text(f"""#!/usr/bin/env bash
case "$*" in
  "compute networks vpc-access connectors describe example-dev-vpc-con"*"--region=europe-west9"*)
    {"exit 0" if connector_found else "echo NOT_FOUND >&2; exit 1"} ;;
  *) echo "unexpected: $*" >&2; exit 1 ;;
esac
""")
    gcloud.chmod(0o755)
    env_file = tmp_path / "github_env"
    env_file.write_text("")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "TARGET_ENV": "dev",
        "SPONSOR_ID": "example",
        "GCP_PROJECT_ID": "example-proj-dev",
        "GCP_REGION": "europe-west9",
        "GITHUB_ENV": str(env_file),
    }
    proc = subprocess.run(["bash", "-c", LOCATE], env=env, capture_output=True, text=True)
    proc.env = env_file.read_text()  # type: ignore[attr-defined]
    return proc


# Verifies: HHT-OPS-sponsor-name-is-data/B
def test_connector_in_the_declared_region_is_used(tmp_path):
    r = _locate(tmp_path, connector_found=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "VPC_CONNECTOR=example-dev-vpc-con" in r.env


# Verifies: HHT-OPS-sponsor-name-is-data/B
def test_connector_outside_the_declared_region_is_refused(tmp_path):
    r = _locate(tmp_path, connector_found=False)
    assert r.returncode != 0
    assert "example-dev-vpc-con" in r.stdout
    assert r.env == ""


def test_reset_reads_no_terraform_written_variable():
    for name in ("GCP_PROJECT_ID", "GCP_REGION", "VPC_CONNECTOR", "DOPPLER_RUNTIME_AUDIENCE"):
        assert f"vars.{name}" not in TEXT


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


def _slack_check(token):
    env = {**os.environ, "SLACK_APP_OATH_TOKEN": token}
    return subprocess.run(["bash", "-c", _run_body(TEXT, "Warn when no Slack token is configured")], env=env, capture_output=True, text=True)


def test_missing_slack_token_warns_and_continues():
    """An operator-triggered non-production reset proceeds without Slack, but
    says so where the operator is watching."""
    r = _slack_check("")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "::warning::" in r.stdout
    assert "SLACK_APP_OATH_TOKEN" in r.stdout


def test_present_slack_token_is_silent():
    r = _slack_check("xoxb-example")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "::warning::" not in r.stdout


def test_slack_warning_is_raised_before_the_approval():
    names = [s["name"] for s in DOC["jobs"]["resolve"]["steps"]]
    assert "Warn when no Slack token is configured" in names
    assert DOC[True]["workflow_call"]["secrets"]["SLACK_APP_OATH_TOKEN"]["required"] is False


def test_slack_notifications_are_skipped_without_a_token():
    spec = DOC["jobs"]["reset"]
    assert spec["env"]["SLACK_CONFIGURED"] == "${{ secrets.SLACK_APP_OATH_TOKEN != '' }}"
    notify = [s for s in spec["steps"] if "slack-notify" in s.get("uses", "")]
    assert notify
    for step in notify:
        assert "env.SLACK_CONFIGURED == 'true'" in step["if"], step["name"]


def test_resolve_job_exposes_the_declared_region_and_audience():
    """The reset job reads these from the resolve job; a step output the job
    does not expose reaches it as an empty string."""
    outputs = DOC["jobs"]["resolve"]["outputs"]
    assert outputs["region"] == "${{ steps.identity.outputs.region }}"
    assert outputs["doppler_audience"] == "${{ steps.identity.outputs.doppler_audience }}"


def _summary(tmp_path, status):
    summary = tmp_path / "summary.md"
    env = {
        **os.environ,
        "TARGET_ENV": "dev",
        "GCP_PROJECT_ID": "example-dev",
        "JOB_STATUS": status,
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    r = subprocess.run(["bash", "-c", _run_body(TEXT, "Summary")], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return summary.read_text()


def test_summary_reports_the_reset_on_success(tmp_path):
    text = _summary(tmp_path, "success")
    assert "dropped" in text
    assert "deploy must follow" in text


@pytest.mark.parametrize("status", ["failure", "cancelled"])
def test_summary_does_not_claim_a_reset_that_did_not_finish(tmp_path, status):
    text = _summary(tmp_path, status)
    assert "dropped" not in text
    assert status in text
    assert "failed step" in text


def test_summary_is_given_the_job_status():
    step = next(s for s in DOC["jobs"]["reset"]["steps"] if s.get("name") == "Summary")
    assert step["env"]["JOB_STATUS"] == "${{ job.status }}"
