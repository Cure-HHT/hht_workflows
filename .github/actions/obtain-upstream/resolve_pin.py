"""Resolve a pinned upstream commit to the artifact reference that carries it.

An upstream publishes one artifact per commit on its main line, tagged by that
commit, so a pin resolves to exactly one reference. There is no search and no
fallback: if the artifact is absent the caller fails rather than reaching for
something nearby, because a consumer that quietly reads a neighbouring revision
produces reports and deliverables describing code it did not use.

Uppercase hex is refused rather than normalised. Lowercasing it would make the
pin a reviewer reads differ from the pin that resolved, which is the same class
of silent substitution, just smaller.
"""

from __future__ import annotations

import re
import sys

_SHA = re.compile(r"^[0-9a-f]{40}$")
# Lowercase, because a registry reference is lowercase and nothing here may
# quietly change what the pin said. An uppercase owner passes every check that
# reads it as text and then fails at the registry, reported as an artifact that
# was never published -- which sends the reader to the upstream's publish run
# rather than to the pin in front of them.
_REPOSITORY = re.compile(r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$")


class PinError(Exception):
    """A pin that cannot name exactly one artifact."""


def image_reference(registry: str, repository: str, commit: str) -> str:
    """Return the artifact reference a pinned commit resolves to.

    Raises PinError if the inputs cannot name exactly one artifact.
    """
    if not repository:
        raise PinError("repository must be given as owner/name")
    if not _REPOSITORY.match(repository):
        raise PinError(
            f"repository must be lowercase owner/name; got {repository!r}"
        )
    if not _SHA.match(commit):
        raise PinError(
            f"pin must be 40 hex characters, lowercase; got {commit!r}"
        )
    return f"{registry}/{repository}:commit-{commit}"


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(
            "usage: resolve_pin.py <registry> <repository> <commit>",
            file=sys.stderr,
        )
        return 2
    try:
        print(image_reference(argv[1], argv[2], argv[3]))
    except PinError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
