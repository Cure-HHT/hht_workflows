#!/usr/bin/env bash
# Materialise another repository's whole content at a pinned commit, once.
#
# The logic lives here rather than inline in action.yml so that both entry
# points -- the composite action, and any step that must obtain several
# upstreams in a loop -- run the same implementation. Two copies of this would
# be two answers to "what does obtaining mean", which is the class of defect
# this action exists to remove.
#
# That includes where a tree lands. The stamp only makes a second request a
# no-op if both entry points derive the same destination for the same pin, so
# the derivation is here too, reachable as `obtain.sh --dest-for <owner/repo>`.
#
# The token arrives in the environment, never as an argument: a command line is
# readable from /proc by every process on the runner, for the lifetime of the
# call.
#
# Usage: obtain.sh <owner/repo> <40-hex commit> <dest> [registry]
#        obtain.sh --dest-for <owner/repo>
# Environment: TOKEN (required, except for --dest-for)
set -euo pipefail

# The repository name becomes a path, so it is checked here, where the
# destination is derived, rather than in a caller. A check in one entry point
# leaves the other able to write outside the runner's temporary directory,
# which is the shape of defect this script exists as one copy to prevent.
require_owner_and_name() {
  if ! printf '%s' "$1" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$' \
     || printf '%s' "$1" | grep -q '\(^\|/\)\.\.\?\(/\|$\)'; then
    # stderr, not stdout: --dest-for's caller reads the destination through a
    # command substitution, which would swallow a refusal written beside it.
    echo "::error::'$1' is not owner/repo." >&2
    exit 1
  fi
}

# Owner and name both, because two owners may publish the same repository name
# and a destination keyed on the name alone would land one tree on the other's.
default_dest() {
  require_owner_and_name "$1"
  printf '%s/upstream/%s\n' "${RUNNER_TEMP:?RUNNER_TEMP must be set}" "$1"
}

if [ "${1:-}" = "--dest-for" ]; then
  default_dest "${2:?owner/repo required}"
  exit 0
fi

REPOSITORY="${1:?owner/repo required}"
COMMIT="${2:?commit required}"
dest="${3:?dest required}"
REGISTRY="${4:-ghcr.io}"
ACTOR="${GITHUB_ACTOR:-token}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

require_owner_and_name "$REPOSITORY"

if [ -z "${TOKEN:-}" ]; then
  echo "::error::TOKEN must be set in the environment to obtain $REPOSITORY."
  exit 1
fi

# An absent stamp is the ordinary first-call case, not an error, so its
# non-zero exit is tolerated here and only here. Any other failure of
# the reader still surfaces, because the value simply will not match.
existing=""
if stamped="$(python3 "${HERE}/stamp.py" --read "$dest" 2>/dev/null)"; then
  existing="$stamped"
fi

if [ "$existing" = "$COMMIT" ]; then
  echo "already materialised at $dest ($COMMIT); not copying again"
  exit 0
fi

ref="$(python3 "${HERE}/resolve_pin.py" "$REGISTRY" "$REPOSITORY" "$COMMIT")"

printf '%s' "$TOKEN" | docker login "$REGISTRY" -u "$ACTOR" --password-stdin

if ! docker pull "$ref"; then
  echo "::error::no artifact published for $REPOSITORY at $COMMIT."
  echo "::error::Looked for: $ref"
  echo "::error::The upstream publishes one artifact per commit on its main line."
  echo "::error::A pin naming a commit that published nothing cannot be resolved,"
  echo "::error::and this action will not fall back to a nearby revision."
  exit 1
fi

digest="$(docker image inspect "$ref" --format '{{index .RepoDigests 0}}')"

mkdir -p "$dest"
cid="$(docker create "$ref")"
docker cp "$cid:/upstream/." "$dest"
docker rm "$cid" > /dev/null

printf '%s\n' "$digest" > "$dest/.upstream-digest"
python3 "${HERE}/stamp.py" --write "$dest" "$COMMIT"

echo "materialised $REPOSITORY at $COMMIT -> $dest"
