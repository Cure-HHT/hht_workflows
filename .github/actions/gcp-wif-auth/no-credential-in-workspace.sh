#!/usr/bin/env bash
# Refuse if the authentication step left a credential inside the workspace.
#
# google-github-actions/auth writes `gha-creds-<random>.json` into
# $GITHUB_WORKSPACE and offers no input to move it. The preceding step moves
# the file out and rewrites the variables that name it. That move depends on an
# implementation detail of a pinned third-party action -- which file it writes,
# and that it reports the path it wrote -- so it is checked rather than
# trusted: a version bump that changes either must fail here, not by publishing
# the credential from whatever captures the workspace next.
#
# Two checks, because neither covers the other. The workspace scan looks where
# this version writes, which is the workspace root; it would not see a file
# written into a subdirectory. The reported-path check would, because a path
# under the workspace is refused wherever in it the path points. A version that
# both wrote somewhere new and misreported it is out of reach of either, and
# out of reach of any check that does not walk the whole tree on every run.
#
# Inputs, from the environment:
#   GITHUB_WORKSPACE       the real workspace, which must hold no credential
#   GOOGLE_GHA_CREDS_PATH  where the auth step says it wrote the file
#
# Exit 0 only when a credential was created AND it is outside the workspace.
# "No credential anywhere" is a failure, not a pass: it would mean the auth
# step silently produced nothing while every consumer expects a file.
# Implements: HHT-OPS-identity-over-keys/D
set -euo pipefail

: "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE is not set}"

# `-quit` rather than a pipe to `head`: under `set -o pipefail` a find with
# more than one match can be killed by SIGPIPE when the reader exits, aborting
# this script at 141 with no ::error:: line -- a refusal that does not say what
# it refused.
stray="$(find "${GITHUB_WORKSPACE}" -maxdepth 1 -name 'gha-creds-*.json' -print -quit 2>/dev/null)"
if [ -n "$stray" ]; then
  echo "::error::a credentials file was written into the workspace at ${stray}" >&2
  echo "::error::the relocation in gcp-wif-auth no longer works; do not capture this workspace" >&2
  exit 1
fi

if [ -z "${GOOGLE_GHA_CREDS_PATH:-}" ]; then
  echo "::error::GOOGLE_GHA_CREDS_PATH is unset, so no credentials file was created" >&2
  echo "::error::consumers expecting application default credentials would fail later" >&2
  exit 1
fi

case "${GOOGLE_GHA_CREDS_PATH}" in
  "${GITHUB_WORKSPACE}"/*)
    echo "::error::the credential is inside the workspace: ${GOOGLE_GHA_CREDS_PATH}" >&2
    exit 1
    ;;
esac

echo "credential held outside the workspace"
