"""CLI entry point for the release-notes-update pre-commit hook."""
from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

from release_notes_update import git as git_mod
from release_notes_update.consolidate import consolidate_fragments
from release_notes_update.fragments import (
    fragment_from_commits,
    parse_fragments,
    render_fragment,
)
from release_notes_update.notes import parse_notes, render_notes


_BRANCH_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _slugify_branch(branch: str) -> str:
    """Turn a git branch name (which may contain slashes) into a filename-safe slug."""
    return _BRANCH_SLUG_RE.sub("-", branch).strip("-")


def _read_version(command: str) -> str:
    """Run the user-supplied version command and normalize the output to 'vX.Y.Z+N'."""
    out = subprocess.check_output(command, shell=True, text=True).strip()
    if not out:
        raise SystemExit("release-notes-update: --version-command produced empty output")
    if not out.startswith("v"):
        # Tolerate version strings without the leading 'v' (e.g. "1.2.3+5").
        out = "v" + out
    return out


def _version_sort_key(version: str):
    """Cheap semver+build sort key for the staleness guard. Numeric parts
    compare numerically; non-numeric parts sort after numerics, lexically."""
    body = version.lstrip("v")
    parts = re.split(r"[.+\-]", body)
    key = []
    for p in parts:
        try:
            key.append((0, int(p)))
        except ValueError:
            key.append((1, p))
    return tuple(key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="release-notes-update")
    parser.add_argument("--version-command", required=True)
    parser.add_argument("--notes-file", default="RELEASE_NOTES.md")
    parser.add_argument("--fragments-dir", default=".release-notes")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args(argv)

    repo_root = Path.cwd()
    notes_path = repo_root / args.notes_file
    frag_dir = repo_root / args.fragments_dir
    frag_dir.mkdir(exist_ok=True)

    version = _read_version(args.version_command)
    today = datetime.date.today().isoformat()

    notes_text = notes_path.read_text() if notes_path.exists() else "# Release Notes\n"
    sections = parse_notes(notes_text)

    # Staleness guard: refuse if topmost section is newer than local version.
    if sections:
        top_key = _version_sort_key(sections[0].version)
        local_key = _version_sort_key(version)
        if top_key > local_key:
            print(
                f"release-notes-update: local version is {version} but "
                f"{args.notes_file} has {sections[0].version} on top. "
                f"Rebase onto origin/main and retry.",
                file=sys.stderr,
            )
            return 1

    # Discover pending fragments on origin/main (representing prior merged PRs)
    # and route them into their version sections. Uses the shared
    # parse_fragments() pipeline so this 'retire' path stays in sync with
    # publish.py's 'compile' path (different source, same parsing).
    pending_origin = git_mod.fragments_on_origin_main()
    pending_frags = [frag for _, frag in parse_fragments(pending_origin.items())]
    sections = consolidate_fragments(sections, pending_frags, today=today)

    # Write back RELEASE_NOTES.md if changed.
    new_notes_text = render_notes(sections)
    files_to_stage: list[str] = []
    if new_notes_text != notes_text:
        notes_path.write_text(new_notes_text)
        files_to_stage.append(args.notes_file)

    # Remove the just-consolidated fragments locally.
    for path in pending_origin.keys():
        local = repo_root / path
        if local.exists():
            local.unlink()
            files_to_stage.append(path)

    # Generate / refresh this PR's fragment.
    subjects = git_mod.commit_subjects_since_main()
    branch = git_mod.current_branch()
    if subjects and branch not in ("HEAD", "main"):
        new_frag = fragment_from_commits(subjects, version=version)
        if new_frag.bullets:
            frag_file = frag_dir / f"{_slugify_branch(branch)}.md"
            new_frag_text = render_fragment(new_frag)
            existing = frag_file.read_text() if frag_file.exists() else ""
            if new_frag_text != existing:
                frag_file.write_text(new_frag_text)
                files_to_stage.append(str(frag_file.relative_to(repo_root)))

    git_mod.stage_paths(files_to_stage)
    return 0


if __name__ == "__main__":
    sys.exit(main())
