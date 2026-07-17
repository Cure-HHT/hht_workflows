# `email-notify` composite action

Sends a plain-text email via the **Gmail API** as an org Workspace
sending identity, using **WIF + domain-wide delegation** — no static
keys, no SMTP credentials, nothing stored.

## How it works

1. Takes the caller's existing WIF-minted GCP credentials (see
   [prerequisites](#caller-prerequisites)) and gets an access token via
   `gcloud auth print-access-token`.
2. Signs a JWT **as the Gmail service account** with `sub=<sender>` via
   `iamcredentials signJwt` (domain-wide delegation).
3. Exchanges the signed JWT at the OAuth token endpoint for a
   Gmail-scoped (`gmail.send`) access token, valid < 1 hour.
4. Builds the RFC822 message (base64url `raw`) and calls
   `gmail users.messages.send`.

No credential outlives the job. Email addresses are masked in run logs
(first char + domain, e.g. `o***@example.org`).

## Caller prerequisites

1. The job has **already authenticated to GCP** — e.g. via this repo's
   [`gcp-wif-auth`](../gcp-wif-auth/) composite (which needs
   `id-token: write` on the job). This action does **not** re-implement
   auth.
2. The WIF-impersonated identity holds
   `roles/iam.serviceAccountTokenCreator` on the Gmail service account.
3. The Gmail service account has **domain-wide delegation** with the
   `https://www.googleapis.com/auth/gmail.send` scope granted by the
   Workspace admin, covering the `sender` mailbox's domain.

## Inputs

| Name                    | Required | Default   | Purpose                                                                                          |
|-------------------------|----------|-----------|----------------------------------------------------------------------------------------------------|
| `to`                    | yes      | —         | Recipient address(es), comma-separated.                                                          |
| `subject`               | yes      | —         | Subject line (single line; CR/LF rejected).                                                      |
| `body`                  | yes      | —         | Plain-text body (UTF-8).                                                                         |
| `sender`                | yes      | —         | Workspace email to send as (e.g. `support@anspar.org`).                                          |
| `gmail-service-account` | yes      | —         | DWD SA email (e.g. `org-gmail-sender@cure-hht-admin.iam.gserviceaccount.com`).                   |
| `cc`                    | no       | `""`      | Optional Cc address(es), comma-separated.                                                        |
| `soft-fail`             | no       | `"false"` | When `"true"`, a send failure is a `::warning::` + `status: failed` instead of failing the action. |

## Outputs

| Name         | Description                                                                 |
|--------------|-------------------------------------------------------------------------------|
| `message-id` | Gmail message id of the sent message; empty when the send failed.           |
| `status`     | `sent` on success, `failed` on any failure (auth, JWT mint/exchange, send). |

## Failure semantics

By default a send failure **fails the action** (`::error::`). Set
`soft-fail: "true"` for deploy notifications — a mail-side hiccup must
not break the deploy; the failure is downgraded to a `::warning::` and
callers can branch on `status`.

## Usage

```yaml
permissions:
  id-token: write   # for gcp-wif-auth
  contents: read

steps:
  - name: Authenticate to GCP (WIF)
    uses: Cure-HHT/hht_workflows/.github/actions/gcp-wif-auth@<commit-sha>  # SHA-pin; see top-level README "Pinning & versioning"
    with:
      workload_identity_provider: ${{ vars.WIF_PROVIDER }}
      service_account: ${{ vars.CI_NOTIFY_SA }}

  - name: Email the deploy summary
    uses: Cure-HHT/hht_workflows/.github/actions/email-notify@<commit-sha>
    with:
      to: team@example.org, oncall@example.org
      subject: "[deploy] portal ${{ github.ref_name }} -> qa"
      body: |
        Deploy completed.
        Run: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
      sender: support@anspar.org
      gmail-service-account: org-gmail-sender@cure-hht-admin.iam.gserviceaccount.com
      soft-fail: "true"   # notification failure must not break the deploy
```

## Action version pinning

Consumers **SHA-pin** this action like every other action in the repo
(`@<40-char-sha>`, never `@main` or a moving tag). See the top-level
`README.md` → "Pinning & versioning" for the full policy.
