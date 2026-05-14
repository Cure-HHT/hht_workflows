"""Git interactions for release-notes-update."""
from __future__ import annotations

import subprocess


def current_branch() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
    ).strip()


def commit_subjects_since_main() -> list[str]:
    """Return commit subjects on the current branch since merge-base with origin/main.
    If origin/main is not yet present (fresh repo, no remote), fall back to all
    commits on this branch."""
    try:
        base = subprocess.check_output(
            ["git", "merge-base", "HEAD", "origin/main"], text=True
        ).strip()
    except subprocess.CalledProcessError:
        return subprocess.check_output(
            ["git", "log", "--pretty=%s"], text=True
        ).strip().splitlines()
    out = subprocess.check_output(
        ["git", "log", f"{base}..HEAD", "--pretty=%s"], text=True
    )
    return out.strip().splitlines()


def fragments_on_origin_main() -> dict[str, str]:
    """Return {path: contents} for every fragment file present on origin/main.
    Empty if origin/main lacks the .release-notes/ directory."""
    try:
        listing = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", "origin/main", ".release-notes/"],
            text=True,
        )
    except subprocess.CalledProcessError:
        return {}
    result: dict[str, str] = {}
    for path in listing.strip().splitlines():
        if not path.endswith(".md"):
            continue
        try:
            content = subprocess.check_output(
                ["git", "show", f"origin/main:{path}"], text=True
            )
        except subprocess.CalledProcessError:
            continue
        result[path] = content
    return result


def stage_paths(paths: list[str]) -> None:
    """Stage the given paths via `git add --`. No-op when paths is empty."""
    if not paths:
        return
    subprocess.check_call(["git", "add", "--", *paths])
