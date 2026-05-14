"""Slice the current version's section from RELEASE_NOTES.md for the
release-notes-publish composite action.

Reuses the hook's discovery + parse + dedupe pipeline (parse_fragments,
read_fragments_dir, append_bullets) so the fragment-listing logic isn't
duplicated between the hook's 'retire' path and this 'compile' path.
The CI runner sets PYTHONPATH to include hooks/release-notes-update."""
from __future__ import annotations

import sys
from pathlib import Path

from release_notes_update.fragments import (
    append_bullets,
    parse_fragments,
    read_fragments_dir,
)
from release_notes_update.notes import parse_notes


def slice_release_notes(notes_path: Path, *, fragments_dir: Path) -> dict[str, str]:
    text = notes_path.read_text() if notes_path.exists() else ""
    sections = parse_notes(text)
    if not sections:
        sys.exit(
            f"release-notes-publish: {notes_path} has no version sections. "
            "Did the version-bump PR run pre-commit?"
        )
    top = sections[0]
    # Pull in pending fragments whose version matches the top section.
    matching_bullets: list[str] = []
    for _path, frag in parse_fragments(read_fragments_dir(fragments_dir)):
        if frag.version == top.version:
            matching_bullets.extend(frag.bullets)
    entries = append_bullets(top.entries, matching_bullets)
    return {
        "version": top.version,
        "date": top.date,
        "summary_block": top.summary,
        "entries_block": "\n".join(entries),
    }


def _emit_outputs(result: dict[str, str]) -> None:
    """Write step outputs in GitHub Actions' multiline heredoc format
    (``key<<DELIM\\nvalue\\nDELIM``). When ``$GITHUB_OUTPUT`` is set the
    output is appended there; otherwise the same heredoc form is printed
    to stdout so local debug output matches the CI artefact byte-for-byte."""
    import os
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        for k, v in result.items():
            print(f"{k}<<EOF\n{v}\nEOF")
        return
    with open(output_path, "a") as f:
        for k, v in result.items():
            f.write(f"{k}<<HHT_EOF\n{v}\nHHT_EOF\n")


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="release-notes-publish")
    parser.add_argument("--notes-file", default="RELEASE_NOTES.md")
    parser.add_argument("--fragments-dir", default=".release-notes")
    args = parser.parse_args(argv)
    result = slice_release_notes(
        Path(args.notes_file), fragments_dir=Path(args.fragments_dir)
    )
    _emit_outputs(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
