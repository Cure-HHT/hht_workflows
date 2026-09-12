#!/usr/bin/env bash
# Identify the source a compile read, for the provenance record beside the
# deliverables.
#
# Two kinds of tree reach the compile, and only one of them is a git checkout:
#
#   obtained  -- extracted from the artifact its upstream published for a pinned
#                commit. No `.git` at all, so every git lookup fails and the old
#                code recorded the word `unknown` at exactly the moment the
#                source became pinned. `obtain.sh` stamps the tree with the
#                repository and the commit it holds, because it is the only step
#                that knows both without guessing.
#   checkout   -- an operator's working tree, identified by git. This is the
#                path that rebuilds the deliverables today.
#
# The stamp wins where both exist: a stamped tree someone also ran `git init` in
# holds the artifact's content, whatever the working tree's own history says.
#
# Sourced, not executed. Everything here is a function so a caller -- the
# compile, or a test -- gets the same answer from the same code.

# The repository a tree came from, as owner/repo.
source_slug() {
  local root="$1" stamp="$1/.upstream-repo" url

  if [ -f "$stamp" ]; then
    tr -d '[:space:]' < "$stamp"
    printf '\n'
    return 0
  fi

  # An absent remote is the ordinary case for a fixture or a detached tree, not
  # an error: the fall-through below reports what is missing.
  url="$(git -C "$root" remote get-url origin 2>/dev/null)" || url=""
  if [ -n "$url" ]; then
    printf '%s\n' "${url%.git}" | sed -E 's#^.*[/:]([^/]+/[^/]+)$#\1#'
    return 0
  fi

  printf 'unidentified (no .upstream-repo stamp, no git origin remote at %s)\n' "$root"
}

# The revision a tree holds: the pinned commit where one was recorded, and the
# working tree's git description otherwise.
source_version() {
  local root="$1" stamp="$1/.upstream-commit" described

  if [ -f "$stamp" ]; then
    tr -d '[:space:]' < "$stamp"
    printf '\n'
    return 0
  fi

  described="$(git -C "$root" describe --tags --always --dirty 2>/dev/null)" || described=""
  if [ -z "$described" ]; then
    described="$(git -C "$root" rev-parse --short HEAD 2>/dev/null)" || described=""
  fi
  if [ -n "$described" ]; then
    printf '%s\n' "$described"
    return 0
  fi

  printf 'unidentified (no .upstream-commit stamp, no git description at %s)\n' "$root"
}

# The compile pipeline's own identity.
#
# Where the compile runs as a composite action, the action was downloaded as a
# tarball and has no `.git` — so git identifies it as poorly as it identifies an
# obtained tree. GitHub supplies the two values a reviewer actually reads in the
# caller's `uses:` line, and they are more truthful than a description of the
# working tree even where both answer: the reference is what the caller pinned.
# URS_TOOL_* is what the action passes explicitly, so the value is visible where
# the compile is configured. GITHUB_ACTION_* is the runner's own, read as the
# fallback rather than being overridden by it: a caller passing an empty context
# must not blank a variable the runner filled in correctly.
tool_slug() {
  local named="${URS_TOOL_REPOSITORY:-${GITHUB_ACTION_REPOSITORY:-}}"
  if [ -n "$named" ]; then
    printf '%s\n' "$named"
    return 0
  fi
  source_slug "$1"
}

tool_version() {
  local named="${URS_TOOL_REF:-${GITHUB_ACTION_REF:-}}"
  if [ -n "$named" ]; then
    printf '%s\n' "$named"
    return 0
  fi
  source_version "$1"
}
