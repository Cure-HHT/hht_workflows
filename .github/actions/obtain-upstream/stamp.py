"""Record which commit a materialised tree holds.

A run that needs an upstream in several steps should obtain it once. The stamp
is how a later step recognises that the tree already holds the commit it wants,
so the request becomes a no-op rather than a second copy of bytes that are
identical by construction.

The reader strips whitespace: the writer ends the file with a newline so it is
well-formed, and a comparison against the raw bytes would never match.
"""

from __future__ import annotations

import pathlib
import sys

_NAME = ".upstream-commit"


def read_stamp(dest: str) -> str | None:
    """Return the commit the tree at `dest` holds, or None if it holds none."""
    path = pathlib.Path(dest, _NAME)
    if not path.is_file():
        return None
    return path.read_text().strip()


def write_stamp(dest: str, commit: str) -> None:
    """Record that the tree at `dest` holds `commit`, creating it if absent."""
    pathlib.Path(dest).mkdir(parents=True, exist_ok=True)
    pathlib.Path(dest, _NAME).write_text(commit + "\n")


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "--read":
        value = read_stamp(argv[2])
        if value is None:
            return 1
        print(value)
        return 0
    if len(argv) == 4 and argv[1] == "--write":
        write_stamp(argv[2], argv[3])
        return 0
    print(
        "usage: stamp.py --read <dest> | --write <dest> <commit>",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
