"""Offline tests for the reusable Cloud Run deploy workflow.

The deploy reads a sponsor's identity from the caller's sponsor.toml and its
per-environment facts from the bound GitHub environment's variables. Both reads
are where a wrong value would deploy one environment's image into another, so
both are exercised here against fixtures rather than trusted to review.

Each step's `run:` body is extracted verbatim from deploy-cloud-run.yml, so the
test cannot drift from the workflow, and driven in a temporary directory that
stands in for the caller's checkout. Exit codes AND the `::error::` text are
asserted, because an operator reading a refusal needs to know which one it is.
"""
import json
import os
import pathlib
import re
import subprocess

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/deploy-cloud-run.yml"
TEXT = WORKFLOW.read_text()
DOC = yaml.safe_load(TEXT)


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


IDENTITY = _run_body(TEXT, "Read the sponsor identity")
RUNTIME_IDENTITY = _run_body(TEXT, "Confirm the environment names its runtime identity")
LOCATE = _run_body(TEXT, "Locate the environment's database and VPC connector")
ENV_VARS = _run_body(TEXT, "Compute deploy env vars")

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

[environments.uat]
gcp_project_id = "example-proj-uat"
portal_domain = "portal.example.org"
"""

BASE_CONFIG = """\
{
  "upstream_pins": {"hht_diary": "%s", "hht_admin": "%s"},
  "gar": {"host": "region9-docker.pkg.dev", "project": "platform-artifacts"},
  "gcp": {
    "project_number": "123456789012",
    "actions_sa_email": "actions@platform-artifacts.iam.gserviceaccount.com"
  }
}
""" % ("a" * 40, "b" * 40)

DIGEST = "sha256:" + "c" * 64
GOOD_IMAGE = f"region9-docker.pkg.dev/platform-artifacts/example-images/portal-final@{DIGEST}"


def _outputs(path: pathlib.Path) -> dict:
    out = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


@pytest.fixture()
def identity(tmp_path):
    """Run the identity step in a stand-in for the caller's checkout."""

    def _invoke(toml=SPONSOR_TOML, base=BASE_CONFIG, **env_overrides):
        (tmp_path / "deployment").mkdir(exist_ok=True)
        if toml is not None:
            (tmp_path / "sponsor.toml").write_text(toml)
        (tmp_path / "deployment/base-config.json").write_text(base)
        out = tmp_path / "github_output"
        out.write_text("")
        env = {
            **os.environ,
            "TARGET_ENV": "dev",
            "IMAGE_PATH": GOOD_IMAGE,
            "SERVICE_NAME": "portal-service",
            "GITHUB_REPOSITORY": "Example-Org/hht_diary_example",
            "GITHUB_REPOSITORY_OWNER": "Example-Org",
            "GITHUB_OUTPUT": str(out),
            **env_overrides,
        }
        proc = subprocess.run(
            ["bash", "-c", IDENTITY], env=env, cwd=tmp_path,
            capture_output=True, text=True,
        )
        proc.outputs = _outputs(out)  # type: ignore[attr-defined]
        return proc

    return _invoke


# Verifies: HHT-OPS-sponsor-name-is-data/B
def test_identity_is_read_from_sponsor_toml(identity):
    r = identity()
    assert r.returncode == 0, r.stdout + r.stderr
    o = r.outputs
    assert o["sponsor_id"] == "example"
    assert o["doppler_project"] == "example-runtime"
    assert o["declared_project"] == "example-proj-dev"
    assert o["region"] == "europe-west9"
    assert o["doppler_audience"] == "doppler-runtime:example-runtime:dev"
    assert o["record_repository"] == "ghcr.io/example-org/hht_diary_example/pipeline"
    assert o["gcp_project_number"] == "123456789012"
    assert o["gcp_sa_email"] == "actions@platform-artifacts.iam.gserviceaccount.com"
    assert o["portal_domain"] == ""


def test_portal_domain_is_read_for_the_target_environment(identity):
    r = identity(TARGET_ENV="uat")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.outputs["portal_domain"] == "portal.example.org"
    assert r.outputs["declared_project"] == "example-proj-uat"


def test_missing_sponsor_toml_refuses(identity):
    r = identity(toml=None)
    assert r.returncode != 0
    assert "::error::" in r.stdout
    assert "sponsor.toml" in r.stdout


def test_environment_not_declared_refuses(identity):
    """An environment is deployable only once sponsor.toml declares it."""
    r = identity(TARGET_ENV="qa")
    assert r.returncode != 0
    assert "'qa' is not declared" in r.stdout


def test_repository_other_than_declared_refuses(identity):
    """A sponsor.toml copied from another repository must not deploy here."""
    r = identity(GITHUB_REPOSITORY="Example-Org/some_other_repo")
    assert r.returncode != 0
    assert "declares repository 'hht_diary_example'" in r.stdout


def test_image_from_another_registry_repository_refuses(identity):
    other = GOOD_IMAGE.replace("/example-images/", "/other-images/")
    r = identity(IMAGE_PATH=other)
    assert r.returncode != 0
    assert "image_path must be an immutable digest reference" in r.stdout


def test_image_by_tag_refuses(identity):
    r = identity(IMAGE_PATH=GOOD_IMAGE.split("@")[0] + ":latest")
    assert r.returncode != 0
    assert "image_path must be an immutable digest reference" in r.stdout


@pytest.mark.parametrize(
    "half",
    [{"VERIFY_SOURCE_PROJECT": "example-proj-qa"}, {"EXPECTED_DIGEST": GOOD_IMAGE}],
)
def test_half_supplied_recheck_refuses(identity, half):
    """One recheck input without the other would silently skip the recheck."""
    r = identity(**half)
    assert r.returncode != 0
    assert "verify_source_project and expected_digest" in r.stdout


def test_complete_recheck_inputs_pass(identity):
    r = identity(VERIFY_SOURCE_PROJECT="example-proj-qa", EXPECTED_DIGEST=GOOD_IMAGE)
    assert r.returncode == 0, r.stdout + r.stderr


def test_unknown_service_refuses(identity):
    r = identity(SERVICE_NAME="diary-service")
    assert r.returncode != 0
    assert "service-name must be 'portal-service'" in r.stdout


def test_platform_constant_missing_refuses(identity):
    r = identity(base='{"gar": {"host": "region9-docker.pkg.dev"}}')
    assert r.returncode != 0
    assert "gar.project" in r.stdout


def test_invalid_identity_refuses(identity):
    r = identity(toml=SPONSOR_TOML.replace('id = "example"', 'id = ""'))
    assert r.returncode != 0
    assert "id" in r.stdout


# Verifies: HHT-OPS-sponsor-name-is-data/B
def test_missing_region_refuses(identity):
    r = identity(toml=SPONSOR_TOML.replace('region = "europe-west9"\n', ""))
    assert r.returncode != 0
    assert "region must be a non-empty string" in r.stdout


# Verifies: HHT-OPS-identity-over-keys/F
def test_environment_without_a_runtime_identity_refuses():
    env = {**os.environ, "TARGET_ENV": "dev", "DOPPLER_RUNTIME_IDENTITY_ID": ""}
    r = subprocess.run(["bash", "-c", RUNTIME_IDENTITY], env=env, capture_output=True, text=True)
    assert r.returncode != 0
    assert "DOPPLER_RUNTIME_IDENTITY_ID" in r.stdout


def _instance(region="europe-west9", name="example-dev-db"):
    return {"name": name, "region": region,
            "connectionName": f"example-proj-dev:{region}:{name}"}


@pytest.fixture()
def locate(tmp_path):
    """Run the lookup step against a stub gcloud. `instances` is what the
    Cloud SQL listing returns (None: the listing fails); `connector_region`
    is where the named connector exists (None: nowhere)."""

    def _invoke(instances=(_instance(),), connector_region="europe-west9"):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        (tmp_path / "instances.json").write_text(json.dumps(list(instances or [])))
        gcloud = bin_dir / "gcloud"
        gcloud.write_text(f"""#!/usr/bin/env bash
echo "$*" >> '{tmp_path / "calls"}'
case "$*" in
  "sql instances list"*)
    {"exit 1" if instances is None else f"cat '{tmp_path / 'instances.json'}'"} ;;
  "compute networks vpc-access connectors describe example-dev-vpc-con"*"--region=europe-west9"*)
    {"exit 0" if connector_region == "europe-west9" else "echo NOT_FOUND >&2; exit 1"} ;;
  "compute networks vpc-access connectors describe"*)
    echo NOT_FOUND >&2; exit 1 ;;
  *) exit 0 ;;
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
            "DOPPLER_PROJECT": "example-runtime",
            "IMAGE_PATH": GOOD_IMAGE,
            "GITHUB_ENV": str(env_file),
        }
        proc = subprocess.run(["bash", "-c", LOCATE], env=env, capture_output=True, text=True)
        proc.env = _outputs(env_file)  # type: ignore[attr-defined]
        proc.calls = (tmp_path / "calls").read_text() if (tmp_path / "calls").exists() else ""  # type: ignore[attr-defined]
        return proc

    return _invoke


# Verifies: HHT-OPS-sponsor-name-is-data/B
def test_database_and_connector_in_the_declared_region_are_used(locate):
    r = locate()
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.env["CLOUD_SQL_CONNECTION"] == "example-proj-dev:europe-west9:example-dev-db"
    assert r.env["VPC_CONNECTOR"] == "example-dev-vpc-con"


def test_database_lookup_selects_this_environments_terraform_instance(locate):
    """Cloud SQL carries user labels under settings.userLabels; a top-level
    labels filter matches no instance at all."""
    r = locate()
    assert "settings.userLabels.environment=dev" in r.calls
    assert "settings.userLabels.managed_by=terraform" in r.calls
    assert "settings.userLabels.sponsor=example" in r.calls


def test_no_database_refuses(locate):
    r = locate(instances=[])
    assert r.returncode != 0
    assert "no Cloud SQL instance" in r.stdout
    assert r.env == {}


def test_several_databases_refuse(locate):
    r = locate(instances=[_instance(), _instance(name="example-dev-db-2")])
    assert r.returncode != 0
    assert "more than one Cloud SQL instance" in r.stdout
    assert r.env == {}


def test_database_lookup_failure_refuses(locate):
    r = locate(instances=None)
    assert r.returncode != 0
    assert r.env == {}


# Verifies: HHT-OPS-sponsor-name-is-data/B
def test_database_outside_the_declared_region_refuses(locate):
    """sponsor.toml's region is the sponsor's residency choice."""
    r = locate(instances=[_instance(region="us-central1")])
    assert r.returncode != 0
    assert "sponsor.toml declares europe-west9" in r.stdout
    assert r.env == {}


# Verifies: HHT-OPS-sponsor-name-is-data/B
def test_connector_outside_the_declared_region_refuses(locate):
    r = locate(connector_region=None)
    assert r.returncode != 0
    assert "example-dev-vpc-con" in r.stdout
    assert r.env == {}


def test_deploy_reads_no_terraform_written_variable():
    """Only the runtime identity, written by the org administration
    repository, is read from the GitHub environment."""
    for name in ("GCP_PROJECT_ID", "GCP_REGION", "CLOUD_SQL_CONNECTION",
                 "VPC_CONNECTOR", "DOPPLER_RUNTIME_AUDIENCE"):
        assert f"vars.{name}" not in TEXT


def _env_vars(tmp_path, **overrides):
    out = tmp_path / "github_output"
    out.write_text("")
    env = {
        **os.environ,
        "TARGET_ENV": "dev",
        "SPONSOR_ID": "example",
        "DOPPLER_PROJECT": "example-runtime",
        "GCP_PROJECT_ID": "example-proj-dev",
        "DOPPLER_RUNTIME_IDENTITY_ID": "00000000-0000-0000-0000-000000000001",
        "DOPPLER_RUNTIME_AUDIENCE": "doppler-runtime:example:dev",
        "DB_BOOT_LOCK_WAIT_SECONDS": "60",
        "GITHUB_RUN_NUMBER": "7",
        "GITHUB_RUN_ID": "99",
        "GITHUB_SHA": "d" * 40,
        "GITHUB_OUTPUT": str(out),
        **overrides,
    }
    proc = subprocess.run(["bash", "-c", ENV_VARS], env=env, capture_output=True, text=True)
    proc.raw = out.read_text()  # type: ignore[attr-defined]
    return proc


# Verifies: HHT-OPS-identity-over-keys/F
def test_revision_gets_the_runtime_identity_and_never_a_token(tmp_path):
    r = _env_vars(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DOPPLER_IDENTITY_ID=00000000-0000-0000-0000-000000000001" in r.raw
    assert "DOPPLER_AUDIENCE=doppler-runtime:example:dev" in r.raw
    assert "DOPPLER_PROJECT_ID=example-runtime" in r.raw
    assert "SPONSOR_ID=example" in r.raw
    assert "DOPPLER_CONFIG_NAME=dev" in r.raw
    assert "remove_env_vars=DOPPLER_TOKEN" in r.raw
    assert "DOPPLER_TOKEN=" not in r.raw.replace("remove_env_vars=DOPPLER_TOKEN", "")


# --- Structure ---------------------------------------------------------------


def test_called_only_never_dispatched():
    """An operator-supplied digest must never reach qa or uat directly; the
    caller owns dispatch and pins it."""
    on = DOC[True] if True in DOC else DOC["on"]
    assert set(on) == {"workflow_call"}


def test_declares_no_concurrency_of_its_own():
    """Callers serialise per environment; a group here would deadlock them."""
    assert "concurrency" not in DOC
    for job in DOC["jobs"].values():
        assert "concurrency" not in job


def test_deploy_job_is_bound_to_a_deployment_environment():
    deploy = DOC["jobs"]["deploy"]
    assert "environment" in deploy
    assert "inputs.target-env" in deploy["environment"]


def test_no_stored_doppler_token_is_read():
    assert "secrets.DOPPLER_TOKEN" not in TEXT


# Verifies: HHT-OPS-sponsor-name-is-data/B
def test_no_sponsor_or_platform_literal_in_the_body():
    """Identity comes from sponsor.toml and platform constants from the
    caller's build configuration; neither is written into this public file."""
    body = "\n".join(
        ln for ln in TEXT.splitlines() if not ln.lstrip().startswith("#")
    )
    for literal in ("pkg.dev/", "iam.gserviceaccount.com", "anspar", "cure-hht-admin"):
        assert literal not in body, literal
    assert not re.search(r"projects/\d+/", body)


def test_every_remote_action_is_pinned_by_commit():
    for ln in TEXT.splitlines():
        m = re.search(r"uses:\s*([^\s#]+)", ln)
        if not m or m.group(1).startswith("./"):
            continue
        ref = m.group(1).split("@", 1)[1]
        assert re.fullmatch(r"[0-9a-f]{40}", ref), ln.strip()


def _slack_check(token):
    env = {**os.environ, "SLACK_APP_OATH_TOKEN": token}
    return subprocess.run(["bash", "-c", _run_body(TEXT, "Require the Slack token")], env=env, capture_output=True, text=True)


def test_missing_slack_token_refuses():
    r = _slack_check("")
    assert r.returncode == 1
    assert "::error::" in r.stdout
    assert "SLACK_APP_OATH_TOKEN" in r.stdout


def test_present_slack_token_passes():
    r = _slack_check("xoxb-example")
    assert r.returncode == 0, r.stdout + r.stderr


def test_slack_token_is_checked_before_anything_else():
    """A deploy without its notification channel must refuse before any job
    builds or deploys, not leave a deployed revision behind a red run."""
    first_jobs = [name for name, job in DOC["jobs"].items() if "needs" not in job]
    assert first_jobs == ["resolve"]
    first_step = DOC["jobs"]["resolve"]["steps"][0]
    assert first_step["name"] == "Require the Slack token"
    assert first_step["env"]["SLACK_APP_OATH_TOKEN"] == "${{ secrets.SLACK_APP_OATH_TOKEN }}"
    assert DOC[True]["workflow_call"]["secrets"]["SLACK_APP_OATH_TOKEN"]["required"] is True


def test_slack_notifications_are_not_gated_on_the_token():
    """The token is guaranteed by the first step, so no notify step may be
    skipped for its absence."""
    assert "SLACK_CONFIGURED" not in TEXT


def test_resolve_job_exposes_the_declared_region_and_audience():
    """The deploy job reads these from the resolve job; a step output the job
    does not expose reaches it as an empty string."""
    outputs = DOC["jobs"]["resolve"]["outputs"]
    assert outputs["region"] == "${{ steps.identity.outputs.region }}"
    assert outputs["doppler_audience"] == "${{ steps.identity.outputs.doppler_audience }}"
