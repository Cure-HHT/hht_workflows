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
# the derivation is here too, reachable as `obtain.sh --dest-for`.
#
# The token arrives in the environment, which is where a secret goes: an
# argument is printed by `set -x` and shown by `ps`.
#
# Usage: obtain.sh <owner/repo> <40-hex commit> <dest> [registry]
#        obtain.sh --dest-for <owner/repo> <40-hex commit>
# Environment: TOKEN (required, except for --dest-for)
set -euo pipefail

# Owner and name both, because two owners may publish the same repository name
# and a destination keyed on the name alone would land one tree on the other's.
default_dest() {
  printf '%s/upstream/%s\n' "${RUNNER_TEMP:?RUNNER_TEMP must be set}" "$1"
}

# `--dest-for <owner/repo> <commit>` answers "where does this pin land", and
# refuses a pin that cannot name an artifact. Validating the commit here rather
# than in a caller means the shape a caller checks is the shape that resolves:
# resolve_pin.py is the rule, and this asks it rather than restating it.
if [ "${1:-}" = "--dest-for" ]; then
  python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve_pin.py" \
    "ghcr.io" "${2:?owner/repo required}" "${3:?commit required}" > /dev/null
  default_dest "$2"
  exit 0
fi

REPOSITORY="${1:?owner/repo required}"
COMMIT="${2:?commit required}"
dest="${3:?dest required}"
REGISTRY="${4:-ghcr.io}"
ACTOR="${GITHUB_ACTOR:-token}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
  # A tree materialised before the slug was recorded holds the right content and
  # a half-written identity. Completing it costs nothing and keeps the no-op
  # path from being the one that yields an unidentifiable provenance row.
  [ -f "$dest/.upstream-repo" ] || printf '%s\n' "$REPOSITORY" > "$dest/.upstream-repo"
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

# The tree is assembled beside the destination and swapped in, because copying
# over whatever is already there makes the result the union of every pin the
# destination has held. A file that outlives its deletion upstream is a
# requirement the deliverable enumerates and the commit it names does not
# contain -- the divergence this action exists to make inexpressible.
#
# The destination is replaced, which the `dest` input says. mktemp is 0700 and
# the swap would make that the tree's mode, so it is widened to match what a
# plain mkdir would have produced.
mkdir -p "${RUNNER_TEMP:?RUNNER_TEMP must be set}"
staging="$(mktemp -d "${RUNNER_TEMP}/obtain.XXXXXX")"
cid="$(docker create "$ref")"
docker cp "$cid:/upstream/." "$staging"
docker rm "$cid" > /dev/null

printf '%s\n' "$digest" > "$staging/.upstream-digest"
# The repository this tree came from, recorded here because this is the only
# step that knows it. A consumer reading the extracted tree can otherwise infer
# no more than its directory name, which names a destination rather than a repo.
printf '%s\n' "$REPOSITORY" > "$staging/.upstream-repo"
python3 "${HERE}/stamp.py" --write "$staging" "$COMMIT"

chmod 755 "$staging"
mkdir -p "$(dirname "$dest")"
rm -rf "$dest"
mv "$staging" "$dest"

echo "materialised $REPOSITORY at $COMMIT -> $dest"
