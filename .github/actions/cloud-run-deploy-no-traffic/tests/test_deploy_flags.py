"""Offline tests for the cloud-run-deploy-no-traffic action's deploy step.

The step is extracted from ``action.yml`` and run against a stub ``gcloud``
that records each argv, so the exact calls a deploy makes are asserted.

Verifies: DIARY-OPS-deploy-traffic-gating/A
"""
import json
import os
import subprocess
from pathlib import Path

import yaml

ACTION = Path(__file__).resolve().parents[1] / "action.yml"
STEP = next(
    s for s in yaml.safe_load(ACTION.read_text())["runs"]["steps"]
    if s["id"] == "deploy"
)

IMAGE = "region9-docker.pkg.dev/platform/images/portal@sha256:" + "a" * 64
CREATED = "portal-service-00042-xyz"
URL = "https://candidate---portal-service-abc.a.run.app"
TRAFFIC = [
    {"revisionName": "portal-service-00041-old", "tags": []},
    {"revisionName": CREATED, "tags": [{"tag": "candidate", "url": URL}]},
]
COMMON = ["portal-service", "--region=europe-west9", "--project=example-proj-dev"]


def _deploy(tmp_path, remove_env_vars):
    """Run the step against a stub gcloud; return its gcloud argvs and outputs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.jsonl"
    (bin_dir / "gcloud").write_text(f"""#!/usr/bin/env python3
import json, sys
open({str(log)!r}, "a").write(json.dumps(sys.argv[1:]) + "\\n")
print({CREATED!r} if sys.argv[3] == "update" else {json.dumps(TRAFFIC)!r})
""")
    (bin_dir / "gcloud").chmod(0o755)
    outputs = tmp_path / "github_output"
    outputs.write_text("")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(outputs),
        "SERVICE": "portal-service",
        "REGION": "europe-west9",
        "PROJECT": "example-proj-dev",
        "IMAGE": IMAGE,
        "TAG": "candidate",
        "UPDATE_ENV_VARS": "ENVIRONMENT=dev,SPONSOR_ID=example",
        "REMOVE_ENV_VARS": remove_env_vars,
    }
    proc = subprocess.run(
        ["bash", "-c", STEP["run"]], env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return calls, outputs.read_text().splitlines()


def _expected(remove_flags):
    return [
        ["run", "services", "update", *COMMON,
         f"--image={IMAGE}", "--no-traffic",
         "--update-env-vars=ENVIRONMENT=dev,SPONSOR_ID=example", *remove_flags,
         "--format=value(status.latestCreatedRevisionName)"],
        ["run", "services", "update-traffic", *COMMON,
         f"--update-tags=candidate={CREATED}", "--format=json"],
    ]


def test_deploy_updates_image_and_env_then_tags_the_created_revision(tmp_path):
    """Update sets only image and env vars; a traffic update tags the revision."""
    calls, outputs = _deploy(tmp_path, "")
    assert calls == _expected([])
    assert outputs == [f"revision_name={CREATED}", f"tagged_url={URL}"]


def test_deploy_removes_named_env_vars(tmp_path):
    """Named env vars are removed on the same update."""
    calls, outputs = _deploy(tmp_path, "DOPPLER_TOKEN")
    assert calls == _expected(["--remove-env-vars=DOPPLER_TOKEN"])
    assert outputs == [f"revision_name={CREATED}", f"tagged_url={URL}"]
