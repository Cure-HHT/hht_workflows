"""Parse the `associates` input of the elspais-federate action.

The input is a newline-separated list of `owner/repo` entries. Blank lines and
`#` comments are ignored so a caller can annotate its list.

Implements: HHT-OPS-repo-bootstrap/I
"""

from __future__ import annotations

import os
import re
import sys

_ENTRY = re.compile(
    r"^(?=[A-Za-z0-9._-]*[A-Za-z0-9])[A-Za-z0-9._-]+/(?=[A-Za-z0-9._-]*[A-Za-z0-9])[A-Za-z0-9._-]+$"
)


def parse_associates(raw: str) -> list[str]:
    """Return normalized, de-duplicated `owner/repo` entries, order preserved.

    Each segment (owner and repo) must contain at least one alphanumeric character.
    Raises ValueError naming the offending entry when one is not `owner/repo` or
    contains a segment with no alphanumeric characters.
    """
    seen: set[str] = set()
    out: list[str] = []
    for line in (raw or "").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if not _ENTRY.match(entry):
            raise ValueError(
                f"associates entry is not in 'owner/repo' form: {entry}"
            )
        if entry not in seen:
            seen.add(entry)
            out.append(entry)
    return out


def main() -> int:
    try:
        for entry in parse_associates(os.environ.get("ASSOCIATES", "")):
            print(entry)
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
