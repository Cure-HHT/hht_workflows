#!/usr/bin/env bash
# Move the credentials file out of the workspace, and tell everything where it
# went.
#
# google-github-actions/auth writes `gha-creds-<random>.json` into
# $GITHUB_WORKSPACE and offers no input to move it: the path is built from that
# variable, and `credentials_file_path` is an output rather than an input.
#
# Overriding GITHUB_WORKSPACE for the auth step would be the tidier fix, but
# GitHub documents the default GITHUB_* variables as not overwritable, so
# whether it works is a property of the runner rather than of this repository.
# Moving the file afterwards depends on nothing but the filesystem.
#
# The file therefore exists inside the workspace between the auth step and this
# one. That window is closed by construction: these are consecutive steps of a
# single composite action, and a consumer's own steps -- including anything
# that captures the workspace -- cannot interleave with them.
#
# Inputs, from the environment:
#   GOOGLE_GHA_CREDS_PATH  where the auth step wrote the file
#   RUNNER_TEMP            outside the workspace, same filesystem, discarded
#                          with the runner
#   GITHUB_ENV             where the corrected paths are exported
set -euo pipefail

: "${RUNNER_TEMP:?RUNNER_TEMP is not set}"
: "${GITHUB_ENV:?GITHUB_ENV is not set}"

if [ -z "${GOOGLE_GHA_CREDS_PATH:-}" ]; then
  echo "::error::GOOGLE_GHA_CREDS_PATH is unset, so no credentials file was created" >&2
  echo "::error::gcp-wif-auth sets export_environment_variables: true, so this means the auth step did not run or did not create one" >&2
  exit 1
fi

if [ ! -f "${GOOGLE_GHA_CREDS_PATH}" ]; then
  echo "::error::GOOGLE_GHA_CREDS_PATH names ${GOOGLE_GHA_CREDS_PATH}, which does not exist" >&2
  exit 1
fi

dest_dir="${RUNNER_TEMP}/gcp-wif-auth"
mkdir -p "$dest_dir"
chmod 700 "$dest_dir"
dest="${dest_dir}/$(basename "${GOOGLE_GHA_CREDS_PATH}")"

# Same filesystem, so this is a rename: no copy is left behind for a capture to
# find. Across filesystems `mv` would copy and unlink, which is still correct
# but leaves the bytes recoverable; RUNNER_TEMP and the workspace are both on
# the runner's work volume.
mv "${GOOGLE_GHA_CREDS_PATH}" "$dest"
chmod 600 "$dest"

# Every consumer of the credential reads one of these, and the upstream post
# step removes GOOGLE_GHA_CREDS_PATH at job end -- reading it from the
# environment at cleanup time, so the cleanup follows the move. Writing all
# three keeps a consumer from finding a stale path in whichever one it happens
# to use.
{
  echo "GOOGLE_APPLICATION_CREDENTIALS=${dest}"
  echo "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE=${dest}"
  echo "GOOGLE_GHA_CREDS_PATH=${dest}"
} >> "${GITHUB_ENV}"

echo "credential moved out of the workspace"
