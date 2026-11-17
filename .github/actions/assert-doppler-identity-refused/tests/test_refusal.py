#!/usr/bin/env python3
"""Offline tests for the assert-doppler-identity-refused action.

The action is a recorded refusal: a job that does not run in the bound
environment asks Doppler for an identity and the run fails if a token
comes back. A control that only ever passes cannot be told from one that
cannot fail, so this drives the action's own script against a local HTTP
server standing in for GitHub's OIDC endpoint and Doppler's API, and checks
every branch:

  - 401/403 from Doppler about the token's claims: the action passes, sets
    outcome=refused, and the summary records the refusal with the status,
    Doppler's message and the raw body;
  - a Doppler-shaped 404, or a 401/403 saying the identity is unknown: the
    action FAILS with outcome=unknown-identity, because a refusal of an
    identity that does not exist proves nothing about its binding;
  - 2xx with a token: the action FAILS with outcome=issued, revokes the
    token, reports whether the revoke worked (the `revoked` output), and
    prints the token nowhere -- not in the log, not in the summary, not in
    GITHUB_ENV;
  - 400, 408, 429, a non-Doppler 404, 5xx or no response: the action fails
    with outcome=error, because nothing was shown;
  - an empty identity id, or no id-token permission: the action fails
    before asking anything;
  - the GitHub OIDC fetch failing: the action fails.

The action is two steps: `ask` classifies and always exits 0 with its
outputs written, and the enforcing step fails the action unless the outcome
is `refused`. Both scripts are lifted from the action file and run in
sequence the way the runner runs a composite, so the thing under test is the
thing that runs, and a caller that turns enforcement off still reads every
output.
"""
from __future__ import annotations

import http.server
import json
import os
import pathlib
import subprocess
import tempfile
import threading
import unittest

import yaml

ACTION_DIR = pathlib.Path(__file__).resolve().parents[1]
ACTION = ACTION_DIR / "action.yml"
SECRET_TOKEN = "dp.st.THIS-MUST-NEVER-BE-PRINTED"


def steps() -> list[dict]:
    doc = yaml.safe_load(ACTION.read_text())
    steps = doc["runs"]["steps"]
    assert [s.get("id") for s in steps] == ["ask", None], \
        "the action is the classifying step and the enforcing step; another step is unreviewed here"
    return steps


class Run:
    """What the runner would show for one invocation of the composite."""

    def __init__(self, returncode: int, stdout: str, stderr: str, outputs: dict):
        self.returncode, self.stdout, self.stderr, self.outputs = returncode, stdout, stderr, outputs


class Fake(http.server.BaseHTTPRequestHandler):
    """GitHub's OIDC endpoint and Doppler's auth endpoints, scripted per test."""

    doppler_status = 401
    doppler_body: dict = {"messages": ["Invalid OIDC token claims"]}
    revoke_status = 200
    oidc_status = 200
    requests: list[tuple[str, str, dict]] = []

    def log_message(self, *_):  # keep the test output quiet
        pass

    def _reply(self, status: int, body):
        payload = (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self.requests.append(("GET", self.path, {}))
        if self.path.startswith("/oidc"):
            if self.oidc_status != 200:
                return self._reply(self.oidc_status, {"message": "nope"})
            return self._reply(200, {"value": "github-oidc-jwt"})
        self._reply(404, {})

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        self.requests.append(("POST", self.path, body))
        if self.path == "/v3/auth/oidc":
            return self._reply(self.doppler_status, self.doppler_body)
        if self.path == "/v3/auth/revoke":
            return self._reply(self.revoke_status, {"success": self.revoke_status == 200})
        self._reply(404, {})


class TestAssertDopplerIdentityRefused(unittest.TestCase):
    def setUp(self):
        Fake.requests = []
        Fake.doppler_status = 401
        Fake.doppler_body = {"messages": ["Invalid OIDC token claims"]}
        Fake.revoke_status = 200
        Fake.oidc_status = 200
        self.server = http.server.HTTPServer(("127.0.0.1", 0), Fake)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        self.summary = pathlib.Path(self.tmp.name, "summary.md")
        self.github_env = pathlib.Path(self.tmp.name, "env")
        self.github_output = pathlib.Path(self.tmp.name, "output")
        self.summary.touch()
        self.github_env.touch()
        self.github_output.touch()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def run_action(self, identity="11111111-2222-3333-4444-555555555555", fail_unless_refused="true", **env):
        base = f"http://127.0.0.1:{self.port}"
        full_env = {
            "PATH": os.environ["PATH"],
            "DOPPLER_IDENTITY_ID": identity,
            "BOUND_ENVIRONMENT": "mobile-prod",
            "OIDC_AUDIENCE": "https://github.com/Cure-HHT",
            "DOPPLER_API_URL": base,
            "ACTIONS_ID_TOKEN_REQUEST_URL": f"{base}/oidc?api-version=2",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "runner-token",
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "GITHUB_ENV": str(self.github_env),
            "GITHUB_OUTPUT": str(self.github_output),
            "GITHUB_JOB": "gate",
            "GITHUB_WORKFLOW_REF": "Cure-HHT/hht_diary/.github/workflows/android-build.yml@refs/heads/main",
            "GITHUB_REPOSITORY": "Cure-HHT/hht_diary",
            "GITHUB_RUN_ID": "123",
        }
        for k, v in env.items():
            if v is None:
                full_env.pop(k, None)
            else:
                full_env[k] = v
        ask, enforce = steps()
        r = subprocess.run(["bash", "-c", ask["run"]], capture_output=True, text=True, env=full_env)
        outputs = self.outputs()
        stdout, stderr, rc = r.stdout, r.stderr, r.returncode
        if rc == 0 and fail_unless_refused != "false":
            # The runner evaluates the step's `if:` and env from the outputs.
            assert enforce["if"] == "inputs.fail_unless_refused != 'false'", enforce["if"]
            assert enforce["env"] == {
                "OUTCOME": "${{ steps.ask.outputs.outcome }}",
                "REASON": "${{ steps.ask.outputs.reason }}",
            }
            e = subprocess.run(
                ["bash", "-c", enforce["run"]], capture_output=True, text=True,
                env={"PATH": os.environ["PATH"], "OUTCOME": outputs.get("outcome", ""),
                     "REASON": outputs.get("reason", "")},
            )
            stdout, stderr, rc = stdout + e.stdout, stderr + e.stderr, e.returncode
        return Run(rc, stdout, stderr, outputs)

    def outputs(self) -> dict:
        out: dict = {}
        for line in self.github_output.read_text().splitlines():
            k, _, v = line.partition("=")
            assert k not in out, f"output {k} written twice"
            out[k] = v
        return out

    def outcome(self):
        lines = [l for l in self.github_output.read_text().splitlines() if l.startswith("outcome=")]
        assert len(lines) == 1, f"outcome must be written exactly once, got {lines}"
        return lines[0].split("=", 1)[1]

    def reset(self):
        Fake.requests = []
        self.summary.write_text("")
        self.github_output.write_text("")

    # Verifies: HHT-OPS-environment-bound-deploy-identity/A
    def test_a_refusal_passes_and_is_recorded(self):
        r = self.run_action()
        assert r.returncode == 0, r.stderr + r.stdout
        assert self.outcome() == "refused"
        summary = self.summary.read_text()
        assert "refused outside `mobile-prod`" in summary, summary
        assert "HTTP 401: Invalid OIDC token claims" in summary, summary
        assert "11111111-2222-3333-4444-555555555555" in summary
        assert "actions/runs/123" in summary
        assert "::notice::Doppler refused identity" in r.stdout
        posts = [p for m, p, _ in Fake.requests if m == "POST"]
        assert posts == ["/v3/auth/oidc"], posts

    # Verifies: HHT-OPS-environment-bound-deploy-identity/A
    def test_the_oidc_exchange_sends_the_identity_and_the_github_token(self):
        self.run_action()
        body = next(b for m, p, b in Fake.requests if p == "/v3/auth/oidc")
        assert body == {"identity": "11111111-2222-3333-4444-555555555555", "token": "github-oidc-jwt"}
        get = next(p for m, p, _ in Fake.requests if m == "GET")
        assert get.endswith("&audience=https%3A%2F%2Fgithub.com%2FCure-HHT"), get

    # Verifies: HHT-OPS-environment-bound-deploy-identity/A
    def test_an_issued_token_fails_the_step_and_is_revoked_unprinted(self):
        Fake.doppler_status = 200
        Fake.doppler_body = {"token": SECRET_TOKEN, "expires_at": "later"}
        r = self.run_action()
        assert r.returncode == 1, "a token means the control is broken; the step must fail"
        assert self.outcome() == "issued"
        assert "::error::[issued] Doppler issued identity" in r.stdout, r.stdout
        assert r.outputs["revoked"] == "yes"
        assert r.outputs["http_status"] == "200"
        revoke = [b for m, p, b in Fake.requests if p == "/v3/auth/revoke"]
        assert revoke == [{"token": SECRET_TOKEN}], Fake.requests
        assert "revoked (HTTP 200)" in self.summary.read_text()
        # The only place the token may appear is the mask directive, which the
        # runner consumes; it must not reach the summary or GITHUB_ENV.
        visible = r.stdout.replace(f"::add-mask::{SECRET_TOKEN}", "") + r.stderr
        assert SECRET_TOKEN not in visible, "token printed"
        assert SECRET_TOKEN not in self.summary.read_text()
        assert self.github_env.read_text() == "", "the token must not be exported"
        assert "accepted a job outside `mobile-prod`" in self.summary.read_text()

    # Verifies: HHT-OPS-environment-bound-deploy-identity/A
    def test_a_failed_revoke_is_reported_and_the_step_still_fails(self):
        Fake.doppler_status = 200
        Fake.doppler_body = {"token": SECRET_TOKEN}
        Fake.revoke_status = 500
        r = self.run_action()
        assert r.returncode == 1
        assert self.outcome() == "issued"
        assert "::warning::The issued token could not be revoked (HTTP 500)" in r.stdout, r.stdout
        assert "revoke FAILED (HTTP 500)" in self.summary.read_text()
        assert r.outputs["revoked"] == "failed"
        assert "has been revoked" not in self.summary.read_text(), "must not claim a revoke that failed"
        visible = r.stdout.replace(f"::add-mask::{SECRET_TOKEN}", "") + r.stderr
        assert SECRET_TOKEN not in visible + self.summary.read_text()

    # Verifies: HHT-OPS-environment-bound-deploy-identity/A
    def test_an_unknown_identity_proves_nothing_and_fails(self):
        # A Doppler-shaped 404 is unambiguous; so is a 401/403 that says so
        # in words. Either way the id variable is stale or the identity was
        # replaced, and recording that as a refusal would be the vacuous pass
        # this test exists to refuse.
        for status, body in ((404, {"messages": ["Not found"]}),
                             (401, {"messages": ["Identity not found"]}),
                             (401, {"messages": ["Invalid identity"]}),
                             (403, {"messages": ["Unknown identity id"]}),
                             (401, {"messages": ["Service account identity does not exist"]})):
            self.reset()
            Fake.doppler_status, Fake.doppler_body = status, body
            r = self.run_action()
            assert r.returncode == 1, (status, body, r.stdout)
            assert self.outcome() == "unknown-identity", (status, body)
            assert "could not be proved refused" in self.summary.read_text(), (status, body)
            assert "refused outside" not in self.summary.read_text(), "must not record a vacuous refusal"
            assert "::error::[unknown-identity] Doppler does not know identity" in r.stdout, r.stdout

    # Verifies: HHT-OPS-environment-bound-deploy-identity/A
    def test_a_claims_refusal_is_not_mistaken_for_an_unknown_identity(self):
        for status, body in ((401, {"messages": ["Invalid OIDC token claims"]}),
                             (401, {"messages": ["The token's sub claim does not match the identity's configuration"]}),
                             (401, {"messages": ["Invalid token: subject claim does not match identity"]}),
                             (403, {"messages": ["Invalid identity token"]}),
                             (401, {"messages": ["Unauthorized"]}),
                             (403, "not json at all")):
            self.reset()
            Fake.doppler_status, Fake.doppler_body = status, body
            r = self.run_action()
            assert r.returncode == 0, (body, r.stdout)
            assert self.outcome() == "refused", body
            assert "refused outside `mobile-prod`" in self.summary.read_text(), body

    # Verifies: HHT-OPS-environment-bound-deploy-identity/A
    def test_a_server_error_proves_nothing_and_fails(self):
        Fake.doppler_status = 503
        Fake.doppler_body = {"messages": ["down"]}
        r = self.run_action()
        assert r.returncode == 1, "silence is not a refusal"
        assert self.outcome() == "error"
        assert "HTTP 503" in r.stdout, r.stdout
        assert self.summary.read_text() == "", "nothing was shown, so nothing is recorded"

    # Verifies: HHT-OPS-environment-bound-deploy-identity/A
    def test_no_response_fails(self):
        # GitHub's OIDC endpoint answers; Doppler's address has nothing
        # listening, so the identity request gets no response at all.
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            dead = s.getsockname()[1]
        r = self.run_action(DOPPLER_API_URL=f"http://127.0.0.1:{dead}")
        assert r.returncode == 1
        assert self.outcome() == "error"
        assert "gave no response" in r.stdout, r.stdout
        assert r.outputs["http_status"] == "000"

    # Verifies: HHT-OPS-environment-bound-deploy-identity/A
    def test_an_empty_identity_fails_before_asking(self):
        r = self.run_action(identity="  ")
        assert r.returncode == 1
        assert self.outcome() == "error"
        assert "No Doppler identity id" in r.stdout, r.stdout
        assert Fake.requests == [], "nothing may be asked without an identity"

    # Verifies: HHT-OPS-environment-bound-deploy-identity/A
    def test_a_failed_github_oidc_fetch_fails(self):
        Fake.oidc_status = 403
        r = self.run_action()
        assert r.returncode == 1
        assert "GitHub OIDC token fetch failed (HTTP 403)" in r.stdout, r.stdout
        assert not any(p == "/v3/auth/oidc" for _, p, _ in Fake.requests)

    # Verifies: HHT-OPS-environment-bound-deploy-identity/A
    def test_only_401_and_403_count_as_a_refusal(self):
        # A rate limit, a timeout or a malformed request is not Doppler
        # saying no to these claims; recording any of them as a refusal is
        # a pass on silence.
        for status, body in ((400, {"messages": ["Invalid request: identity is required"]}),
                             (400, {"messages": ["Invalid OIDC token claims"]}),
                             (408, {"messages": ["Request timeout"]}),
                             (429, {"messages": ["Too many requests"]}),
                             (409, {"messages": ["Conflict"]}),
                             (404, {}),
                             (404, "<html>not found</html>"),
                             (302, {}),
                             (502, {"messages": ["bad gateway"]})):
            self.reset()
            Fake.doppler_status, Fake.doppler_body = status, body
            r = self.run_action()
            assert r.returncode == 1, (status, body, r.stdout)
            assert self.outcome() == "error", (status, body)
            assert r.outputs["http_status"] == str(status), r.outputs
            assert "::error::[error]" in r.stdout, r.stdout
            assert "refused outside" not in self.summary.read_text(), (status, body)

    # Verifies: HHT-OPS-environment-bound-deploy-identity/A
    def test_a_missing_id_token_permission_fails_before_asking(self):
        for missing in ("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_URL"):
            self.reset()
            r = self.run_action(**{missing: None})
            assert r.returncode == 1, (missing, r.stdout)
            assert self.outcome() == "error"
            assert "id-token: write" in r.stdout, r.stdout
            assert Fake.requests == [], "nothing may be asked without an OIDC endpoint"

    # Verifies: HHT-OPS-environment-bound-deploy-identity/A
    def test_the_raw_answer_is_printed_with_tokens_redacted(self):
        # Doppler's wording is documented nowhere, so the first live run must
        # record what it actually said -- without ever printing a token.
        Fake.doppler_status = 401
        Fake.doppler_body = {"messages": ["Invalid token: subject claim does not match identity"],
                             "success": False}
        r = self.run_action()
        assert "HTTP 401" in r.stdout, r.stdout
        assert '"messages":["Invalid token: subject claim does not match identity"]' in r.stdout, r.stdout
        assert "Raw answer" in self.summary.read_text()
        self.reset()
        Fake.doppler_status = 200
        Fake.doppler_body = {"token": SECRET_TOKEN, "nested": {"access_token": SECRET_TOKEN}}
        r = self.run_action()
        visible = r.stdout.replace(f"::add-mask::{SECRET_TOKEN}", "") + r.stderr
        assert SECRET_TOKEN not in visible + self.summary.read_text(), "token printed"
        assert '"token":"<redacted>"' in r.stdout, r.stdout
        assert '"access_token":"<redacted>"' in r.stdout, r.stdout
        # The body cannot issue workflow commands while it is printed.
        assert "::stop-commands::" in r.stdout

    # Verifies: HHT-OPS-environment-bound-deploy-identity/A
    def test_a_non_json_2xx_body_is_withheld(self):
        Fake.doppler_status = 200
        Fake.doppler_body = SECRET_TOKEN
        r = self.run_action()
        assert r.returncode == 1
        assert self.outcome() == "issued"
        assert r.outputs["revoked"] == "no-token"
        assert SECRET_TOKEN not in r.stdout + r.stderr + self.summary.read_text()
        assert "<non-JSON 2xx body withheld>" in r.stdout

    # Verifies: HHT-OPS-environment-bound-deploy-identity/A
    def test_outputs_are_readable_when_enforcement_is_off(self):
        # The readiness job provokes the failing outcomes on purpose and
        # asserts them through the outputs; the classifying step must
        # therefore never fail on a classified answer.
        for status, body, outcome in ((200, {"token": SECRET_TOKEN}, "issued"),
                                      (404, {"messages": ["Not found"]}, "unknown-identity"),
                                      (429, {"messages": ["slow down"]}, "error"),
                                      (401, {"messages": ["Invalid OIDC token claims"]}, "refused")):
            self.reset()
            Fake.doppler_status, Fake.doppler_body = status, body
            r = self.run_action(fail_unless_refused="false")
            assert r.returncode == 0, (status, r.stdout)
            assert r.outputs["outcome"] == outcome, (status, r.outputs)
            assert r.outputs["http_status"] == str(status)
            assert r.outputs["reason"], r.outputs

    # Verifies: HHT-OPS-environment-bound-deploy-identity/A
    def test_every_request_is_bounded_in_time(self):
        # A hung Doppler must end as `error`, not hold the job until the
        # runner's own timeout.
        ask = steps()[0]["run"]
        assert "--connect-timeout 10 --max-time 30" in ask
        assert ask.count("curl ") == 1, "every request goes through http_call"

    # Verifies: HHT-OPS-environment-bound-deploy-identity/A
    def test_the_action_defaults_to_the_real_doppler_api(self):
        # The override exists for this test only; the shipped default must be
        # Doppler's API and the audience the identities are declared with.
        text = ACTION.read_text()
        assert 'DOPPLER_API_URL="${DOPPLER_API_URL:-https://api.doppler.com}"' in text
        doc = yaml.safe_load(text)
        assert doc["inputs"]["audience"]["default"] == "https://github.com/Cure-HHT"
        assert doc["inputs"]["doppler_identity_id"]["required"] is True
        assert doc["inputs"]["environment"]["required"] is True
        assert doc["outputs"]["outcome"]["value"] == "${{ steps.ask.outputs.outcome }}"
        assert doc["runs"]["steps"][0]["id"] == "ask"
        assert doc["inputs"]["fail_unless_refused"]["default"] == "true"
        for name in ("outcome", "http_status", "revoked", "reason"):
            assert doc["outputs"][name]["value"] == "${{ steps.ask.outputs.%s }}" % name


if __name__ == "__main__":
    unittest.main()
