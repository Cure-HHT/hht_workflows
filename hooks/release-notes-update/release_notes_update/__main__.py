"""CLI entry point for the release-notes-update pre-commit hook."""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="release-notes-update")
    parser.add_argument(
        "--version-command",
        required=True,
        help="Shell command whose stdout is the current version (e.g. 'cat VERSION').",
    )
    parser.add_argument(
        "--notes-file",
        default="RELEASE_NOTES.md",
        help="Path to RELEASE_NOTES.md (default: RELEASE_NOTES.md).",
    )
    parser.add_argument(
        "--fragments-dir",
        default=".release-notes",
        help="Directory holding pending fragments (default: .release-notes).",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Files staged for commit (passed by pre-commit framework; unused).",
    )
    parser.parse_args(argv)
    print("release-notes-update: placeholder; implemented in Task 5", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
