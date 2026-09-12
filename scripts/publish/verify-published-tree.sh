#!/usr/bin/env bash
# Confirm a published artifact carries every file tracked at the commit it was
# published for, by comparing counts.
#
# Usage: verify-published-tree.sh <repository root> <extracted artifact root>
#
# Testing for a known path cannot catch the failure this exists for. A
# `.dockerignore` rule applies to a tar build context too, so a rule added for
# some other image silently prunes this artifact -- and the file it removes is,
# by definition, the one nobody thought to list. A consumer pinned to that
# commit then reads a tree that is missing something, with nothing it can
# observe distinguishing a complete artifact from a curated one.
#
# Counting needs no such list. It is the check that does not have to know in
# advance which file went missing.
set -euo pipefail

REPO_ROOT="${1:?repository root required}"
PUBLISHED_ROOT="${2:?extracted artifact root required}"

tracked="$(git -C "$REPO_ROOT" ls-files | wc -l)"
published="$(find "$PUBLISHED_ROOT" -type f | wc -l)"

if [ "$tracked" -ne "$published" ]; then
  echo "::error::artifact carries $published files, but $tracked are tracked at this commit"
  echo "::error::Something is pruning the build context -- check .dockerignore."
  exit 1
fi

echo "artifact carries all $tracked tracked files"
