#!/usr/bin/env bash
# Identify a tree the compile read, for the provenance record beside the
# deliverables.
#
# Two kinds of tree reach the compile, and only one of them answers git:
#
#   obtained  -- extracted from the artifact its upstream published for a
#                pinned commit, with no `.git` at all. `obtain.sh` stamps it
#                with the repository and the commit it holds, because that step
#                is the only one that knows both without guessing.
#   checkout   -- an operator's working tree, identified by git.
#
# A stamp wins over git where both are present: a stamped tree someone also ran
# `git init` in holds the artifact's content, whatever the working tree's own
# history says.
#
# Sourced, not executed, so the compile and its tests answer from one place.

# What the stamp file holds, or nothing when there is no stamp. Command
# substitution strips the trailing newline, which is why the file can end in one.
_stamped() {
  [ -f "$1" ] && printf '%s' "$(cat "$1")"
}

# The repository a tree came from, as owner/repo.
source_slug() {
  local root="$1" stamped url
  stamped="$(_stamped "$root/.upstream-repo")"
  if [ -n "$stamped" ]; then
    printf '%s\n' "$stamped"
    return 0
  fi

  # An absent remote is ordinary for a fixture or a detached tree, not an error:
  # the fall-through reports which identity source was missing.
  url="$(git -C "$root" remote get-url origin 2>/dev/null)" || url=""
  if [ -n "$url" ]; then
    printf '%s\n' "${url%.git}" | sed -E 's#^.*[/:]([^/]+/[^/]+)$#\1#'
    return 0
  fi

  printf 'unidentified (no .upstream-repo stamp, no git origin remote at %s)\n' "$root"
}

# The author a pipeline image gives the repository it initialises over a tree,
# for the tools that require one. That commit names nothing upstream: asking it
# which revision this is returns a plausible wrong answer rather than an error.
PIPELINE_FABRICATED_AUTHOR="pipeline@invalid"

# True when the tree's git history is the one a pipeline image fabricated.
_fabricated_history() {
  local email
  email="$(git -C "$1" log -1 --format=%ae 2>/dev/null)" || return 1
  [ "$email" = "$PIPELINE_FABRICATED_AUTHOR" ]
}

# The revision a tree holds: the pinned commit where one was stamped, and git's
# description of the working tree otherwise. A history the pipeline fabricated
# is refused rather than described: its commit is not the source's.
source_version() {
  local root="$1" stamped described
  stamped="$(_stamped "$root/.upstream-commit")"
  if [ -n "$stamped" ]; then
    printf '%s\n' "$stamped"
    return 0
  fi

  if _fabricated_history "$root"; then
    echo "error: $root carries a history the pipeline fabricated (author $PIPELINE_FABRICATED_AUTHOR) and no .upstream-commit stamp; its git revision names nothing upstream, so it is not reported as one" >&2
    return 1
  fi

  described="$(git -C "$root" describe --tags --always --dirty 2>/dev/null)" || described=""
  if [ -n "$described" ]; then
    printf '%s\n' "$described"
    return 0
  fi

  printf 'unidentified (no .upstream-commit stamp, no git description at %s)\n' "$root"
}

# The full commit a tree holds, for a record that names commits rather than
# descriptions: the stamp where there is one, git's HEAD otherwise, and nothing
# (status 1) where neither answers. A fabricated history is refused as above.
source_commit() {
  local root="$1" stamped sha
  stamped="$(_stamped "$root/.upstream-commit")"
  if [ -n "$stamped" ]; then
    printf '%s\n' "$stamped"
    return 0
  fi
  if _fabricated_history "$root"; then
    echo "error: $root carries a history the pipeline fabricated (author $PIPELINE_FABRICATED_AUTHOR) and no .upstream-commit stamp; its git revision names nothing upstream, so it is not reported as one" >&2
    return 2
  fi
  sha="$(git -C "$root" rev-parse HEAD 2>/dev/null)" || return 1
  printf '%s\n' "$sha"
}

# The image the compile ran in, by digest, or nothing when it ran on a host
# toolchain. A value that is set must name a digest: a tag can move after the
# deliverable is written, and then names a different toolchain than the one
# that produced it.
compile_image() {
  local image="${COMPILE_IMAGE:-}"
  [ -z "$image" ] && return 0
  if ! printf '%s' "$image" | grep -Eq '^[^[:space:]@]+@sha256:[0-9a-f]{64}$'; then
    echo "error: COMPILE_IMAGE must name an image by digest (<name>@sha256:<64 hex>), got '$image'" >&2
    return 1
  fi
  printf '%s\n' "$image"
}

# The compile pipeline's own identity.
#
# Running as a composite action, the pipeline was downloaded as a tarball with
# no `.git`, so git identifies it as poorly as it identifies an obtained tree.
# The invoking reference is both available and more truthful: it is what the
# caller pinned, which a description of a working tree is not.
#
# URS_TOOL_* is what the action passes explicitly, so the value is visible where
# the compile is configured; GITHUB_ACTION_* is the runner's own, read next so
# that an empty explicit value falls through rather than blanking it.
tool_slug() {
  printf '%s\n' "${URS_TOOL_REPOSITORY:-${GITHUB_ACTION_REPOSITORY:-$(source_slug "$1")}}"
}

tool_version() {
  printf '%s\n' "${URS_TOOL_REF:-${GITHUB_ACTION_REF:-$(source_version "$1")}}"
}
