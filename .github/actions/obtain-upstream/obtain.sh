#!/usr/bin/env bash
# Materialise another repository's whole content at a pinned commit, once.
#
# The logic lives here rather than inline in action.yml so that both entry
# points -- the composite action, and any step that must obtain several
# upstreams in a loop -- run the same implementation. Two copies of this would
# be two answers to "what does obtaining mean", which is the class of defect
# this action exists to remove.
#
# Usage: obtain.sh <owner/repo> <40-hex commit> <dest> <token> [registry]
set -euo pipefail

REPOSITORY="${1:?owner/repo required}"
COMMIT="${2:?commit required}"
dest="${3:?dest required}"
TOKEN="${4:?token required}"
REGISTRY="${5:-ghcr.io}"
ACTOR="${GITHUB_ACTOR:-token}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# An absent stamp is the ordinary first-call case, not an error, so its
# non-zero exit is tolerated here and only here. Any other failure of
# the reader still surfaces, because the value simply will not match.
existing=""
if stamped="$(python3 "${HERE}/stamp.py" --read "$dest" 2>/dev/null)"; then
  existing="$stamped"
fi

if [ "$existing" = "$COMMIT" ]; then
  echo "already materialised at $dest ($COMMIT); not copying again"
  # A tree materialised before the slug was recorded holds the right content and
  # a half-written identity. Completing it costs nothing and keeps the no-op
  # path from being the one that yields an unidentifiable provenance row.
  [ -f "$dest/.upstream-repo" ] || printf '%s\n' "$REPOSITORY" > "$dest/.upstream-repo"
  exit 0
fi

ref="$(python3 "${HERE}/resolve_pin.py" "$REGISTRY" "$REPOSITORY" "$COMMIT")"

echo "$TOKEN" | docker login "$REGISTRY" -u "$ACTOR" --password-stdin

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
# The repository this tree came from, recorded here because this is the only
# step that knows it. A consumer reading the extracted tree can otherwise infer
# no more than its directory name, which names a destination rather than a repo.
printf '%s\n' "$REPOSITORY" > "$dest/.upstream-repo"
python3 "${HERE}/stamp.py" --write "$dest" "$COMMIT"

echo "materialised $REPOSITORY at $COMMIT -> $dest"
