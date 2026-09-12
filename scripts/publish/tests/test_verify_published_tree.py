"""What was published carries every tracked file, checked by counting.

The failure this guards is specific and silent: an ignore rule added for some
other purpose applies to the publish build context too and prunes it. The
artifact still pushes, still extracts, and still contains whatever file anyone
thought to test for -- so a spot-check passes while a class of file has
disappeared, which is exactly the divergence publishing a whole tree exists to
remove. The file that goes missing is by definition the one nobody listed.

Counting is the check that does not need to know which file that was.
"""

from __future__ import annotations

import pathlib
import subprocess

VERIFY = pathlib.Path(__file__).resolve().parents[1] / "verify-published-tree.sh"

_GIT_ENV = {
    "PATH": "/usr/bin:/bin",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}

TRACKED = ("pyproject.toml", "README.md", ".hidden-file", "scripts/one.sh")


def _repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """A repository tracking four files, one of them a dotfile."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    for name in TRACKED:
        (root / name).write_text(f"{name}\n")
    subprocess.run(["git", "-C", str(root), "init", "-q"], env=_GIT_ENV, check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], env=_GIT_ENV, check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "one"], env=_GIT_ENV, check=True
    )
    return root


def _published(tmp_path: pathlib.Path, *, omit: str | None = None) -> pathlib.Path:
    """The extracted artifact, optionally missing one file an ignore rule ate."""
    root = tmp_path / "extracted"
    (root / "scripts").mkdir(parents=True)
    for name in TRACKED:
        if name == omit:
            continue
        (root / name).write_text(f"{name}\n")
    return root


def _run(repo: pathlib.Path, published: pathlib.Path):
    return subprocess.run(
        [str(VERIFY), str(repo), str(published)],
        capture_output=True,
        text=True,
    )


def test_a_complete_tree_passes(tmp_path):
    proc = _run(_repo(tmp_path), _published(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "4" in proc.stdout


def test_a_pruned_tree_refuses_and_names_both_counts(tmp_path):
    proc = _run(_repo(tmp_path), _published(tmp_path, omit="scripts/one.sh"))
    assert proc.returncode != 0
    assert "3" in proc.stdout and "4" in proc.stdout


def test_a_pruned_dotfile_is_caught_like_any_other(tmp_path):
    """A dotfile is the likeliest casualty and the least likely to be listed."""
    proc = _run(_repo(tmp_path), _published(tmp_path, omit=".hidden-file"))
    assert proc.returncode != 0


def test_the_refusal_points_at_the_cause(tmp_path):
    proc = _run(_repo(tmp_path), _published(tmp_path, omit="README.md"))
    assert "dockerignore" in (proc.stdout + proc.stderr).lower()


def test_a_symlink_counts_as_published_content(tmp_path):
    """git tracks a symlink as an entry, so the two sides must agree on it.

    Counted on the left and not on the right, a symlink would produce a refusal
    naming a pruning that never happened -- and the next person would learn to
    distrust the check rather than the tree.
    """
    repo = _repo(tmp_path)
    (repo / "link").symlink_to("README.md")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], env=_GIT_ENV, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "link"], env=_GIT_ENV, check=True
    )

    published = _published(tmp_path)
    (published / "link").symlink_to("README.md")

    proc = _run(repo, published)
    assert proc.returncode == 0, proc.stdout + proc.stderr
