#!/usr/bin/env bash
# Turn build-urs's pins into the associate roots the compile federates.
#
# A deliverable enumerates obligations; the build it describes is pinned.
# Obtaining the spec source from the artifact published for that same pin is
# what stops the two being different revisions. Paths are the old way in and
# are refused alongside pins rather than silently losing to them.
#
# This is a script rather than a step body in action.yml so the suite can run
# what actually executes. Nothing else exercises it: the readiness fixture
# supplies paths, so on that route this never runs, and the first caller
# supplying pins is a consumer repository.
#
# Environment:
#   COMMITS        newline-delimited `owner/repo@<40-hex commit>`
#   TOKEN          registry read token, passed onward in the environment
#   PATH_ROOT      the associate-root input, which must be empty
#   PATH_ROOTS     the associate-roots input, which must be empty
#   GITHUB_OUTPUT  where the resolved roots are written
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OBTAIN="${HERE}/../obtain-upstream/obtain.sh"

if [ -n "${PATH_ROOT:-}" ] || [ -n "${PATH_ROOTS:-}" ]; then
  echo "::error::associate-commits was given together with a path input."
  echo "::error::A run supplying both could compile from two revisions"
  echo "::error::while reporting one. Supply the pins alone."
  exit 1
fi
if [ -z "${TOKEN:-}" ]; then
  echo "::error::registry-token is required when associate-commits is set."
  exit 1
fi

# Resolve every entry before obtaining any of them, so a bad pin at the end of
# the list costs nothing that was already fetched for the entries before it.
#
# What makes a pin acceptable is obtain.sh's answer, not a second one here:
# `--dest-for` refuses the pin and yields the destination in one step, so the
# pin that passes is exactly the pin that resolves. A repository named twice is
# refused here, because one destination cannot hold two commits.
repos=()
commits=()
dests=()
declare -A seen_dest=()
while read -r entry; do
  # The default IFS trims the ends; a CRLF input would otherwise carry its
  # return into the repository name. Whitespace inside an entry is left alone,
  # so a typo is refused rather than closed up into a different repository.
  entry="${entry%$'\r'}"
  [ -z "$entry" ] && continue
  repo="${entry%@*}"
  commit="${entry#*@}"
  if [ "$repo" = "$entry" ] || [ -z "$repo" ] || [ -z "$commit" ]; then
    echo "::error::associate-commits entry is not owner/repo@<commit>: '$entry'"
    exit 1
  fi
  # obtain.sh decides what a pin may be and where it lands. A shape rule here
  # would be a second answer to the question resolve_pin.py already answers,
  # and the two would drift apart silently. Asking in the parse pass is what
  # keeps a typo in the fifth entry from surfacing with four trees on disk.
  dest="$("$OBTAIN" --dest-for "$repo" "$commit")"
  if [ -n "${seen_dest[$dest]:-}" ]; then
    echo "::error::associate-commits names '$repo' more than once."
    echo "::error::One repository cannot be at two commits in one compile: one"
    echo "::error::destination holds one of them, and roots would list it twice."
    exit 1
  fi
  seen_dest[$dest]=1
  repos+=("$repo")
  commits+=("$commit")
  dests+=("$dest")
done <<< "${COMMITS:-}"

# A caller that set associate-commits named nothing resolvable. Compiling zero
# associates would federate no cross-repository content and still report a
# deliverable, which is the silent mismatch this route exists to remove.
if [ "${#repos[@]}" -eq 0 ]; then
  echo "::error::associate-commits is set but names no repository."
  exit 1
fi

roots=()
for i in "${!repos[@]}"; do
  # TOKEN travels in the environment it is already in; naming it on the command
  # line would publish it to every process on the runner via /proc.
  "$OBTAIN" "${repos[$i]}" "${commits[$i]}" "${dests[$i]}"
  roots+=("${dests[$i]}")
done

{
  echo "roots<<EOF"
  # No trailing blank line: compile-urs.sh skips them, but a contract that
  # depends on the consumer being tolerant is a contract stated twice.
  printf '%s\n' "${roots[@]}"
  echo "EOF"
} >> "${GITHUB_OUTPUT:?GITHUB_OUTPUT must be set}"
