# assert-doppler-identity-refused

Ask Doppler for a service-account identity this job must **not** be able to
hold, record the refusal in the job summary, and fail the run if a token is
issued.

**Why this exists:** `HHT-OPS-environment-bound-deploy-identity/A` requires a
deploy identity to be issued only to a run bound to its deployment
environment. The binding is declared in `hht_admin` Terraform, where the
consuming repository cannot reach it, but a binding nobody exercises is a
claim rather than a control. This action is the recorded refusal: a job that
does not run in the environment asks for the identity on every run, so the
run page carries the evidence and a loosened binding turns the next ordinary
build red instead of letting the next release through unapproved. It is the
negative form of the Doppler OIDC handshake, kept here per
`HHT-OPS-composite-action-library/A` so no consumer re-implements the exchange
(see `cure-hht/hht_admin/spec/ops-secrets-architecture.md` and
`spec/ops-cicd.md`).

## What happens on each answer from Doppler

The answer is classified by HTTP status first. Doppler's message can only
narrow a 401/403 down to an unknown identity; it never turns any other answer
into a refusal.

| Doppler answers | `outcome` output | Action result | What is left behind |
| --- | --- | --- | --- |
| 401 or 403 that does not say the identity is unknown | `refused` | passes | A summary table: identity, the environment it is bound to, the job and the run it belongs to, the HTTP status, Doppler's message, the run URL, and the raw answer. A `::notice::` in the log. |
| 404 with a Doppler JSON error body, or a 401/403 whose message says the identity is unknown (`Identity not found`, `Unknown identity`, `Invalid identity`, ...) | `unknown-identity` | **fails** | A summary saying the refusal could not be proved: the identity id is stale, or the identity was deleted or replaced. A refusal of an identity that does not exist says nothing about its binding. |
| 2xx | `issued` | **fails** | Any token is masked, revoked through `/v3/auth/revoke` (the `revoked` output and the summary say whether that succeeded), and printed nowhere. The summary and an `::error::` name the identity and the environment it should have been bound to. |
| Anything else: 400, 408, 429, other 4xx, a 404 that is not Doppler's, 3xx, 5xx, no response within 30 s | `error` | **fails** | Nothing in the summary: nothing was proved either way. |
| Nothing asked: empty identity id, or no `id-token: write` on the job | `error` | **fails** | An `::error::` saying which. |

The unknown-identity pattern is deliberately tight: a claims refusal such as
`Invalid token: subject claim does not match identity` stays `refused`.

**Doppler's wording is not documented.** Every run prints Doppler's raw HTTP
status and body in a log group (any field whose name mentions a token is
redacted, a non-JSON 2xx body is withheld, workflow commands are suspended
while it prints), and the summary carries the same raw answer. The readiness
job drives `unknown-identity`, `refused` and `issued` live, so its run is the
record the classification above is checked against; a change in Doppler's
answers turns that job red with the raw answer beside the failure.

The action fetches no secret, writes nothing to `GITHUB_ENV`, and never
prints a token. Because it fails on silence, Doppler's availability gates
every run that carries it. Every request has a 10 s connect and 30 s total
timeout.

## How it is built

Two steps. `ask` makes the requests, classifies the answer, writes the
outputs and the summary, and exits 0 for every classified answer. The second
step fails the action unless `outcome` is `refused`. Splitting them keeps the
outputs readable by a caller that turns enforcement off
(`fail_unless_refused: false`), which only the readiness job does.

## Outputs

| Output | Values |
| --- | --- |
| `outcome` | `refused`, `unknown-identity`, `issued`, `error`. Only `refused` passes the action. |
| `http_status` | Doppler's status for the identity request; `000` for no response; empty when nothing was asked. |
| `revoked` | For `issued`: `yes`, `failed`, or `no-token`. Otherwise `not-applicable`. |
| `reason` | One line saying why. |

## Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `doppler_identity_id` | yes | — | UUID of the Doppler service-account identity that must refuse this job. Pass via `vars.<NAME>`; never hardcode. |
| `environment` | yes | — | The GitHub environment the identity is bound to, for the summary and the failure message. This job must not be running in it. |
| `audience` | no | `https://github.com/Cure-HHT` | The OIDC audience the Doppler identity expects. |
| `fail_unless_refused` | no | `true` | `false` stops the action failing on a non-refused outcome. For this repository's readiness job only; a consumer that sets it has no gate. |

## Usage

The calling job needs `id-token: write`, must **not** bind the environment the
identity is bound to, and must run `actions/checkout` only if it needs the
repository for other steps (this action does not).

```yaml
jobs:
  gate:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
    steps:
      - name: Prove the prod identity refuses a job outside mobile-prod
        uses: Cure-HHT/hht_workflows/.github/actions/assert-doppler-identity-refused@<commit-sha>  # SHA-pin; see "Pinning & versioning"
        with:
          doppler_identity_id: ${{ vars.MOBILE_BUILD_PROD_DOPPLER_IDENTITY_ID }}
          environment: mobile-prod
```

Run it unconditionally. A condition on the step is a way to stop recording
the refusal.

## Tests

`tests/test_refusal.py` runs the action's two step scripts in sequence, as the
runner does, against a local HTTP server standing in for GitHub's OIDC
endpoint and Doppler's API, through every row above: claims refusals in
several wordings (including `Invalid token: subject claim does not match
identity`), unknown identities in several wordings, 400/408/409/429/502, a
non-Doppler 404, no response, a missing id-token permission, an issued token
(revoked, a failed revoke reported rather than claimed, the token printed
nowhere including in the raw answer), and the outputs with enforcement off.
The readiness job in `readiness-checks.yml` drives `unknown-identity`,
`refused` (the readiness identity asked for with a wrong audience) and
`issued` live against Doppler.
