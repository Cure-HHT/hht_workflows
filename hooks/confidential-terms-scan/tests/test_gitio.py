import subprocess

import pytest

from confidential_terms_scan.gitio import (
    EMPTY_TREE,
    ZERO_SHA,
    added_lines,
    added_or_renamed_paths,
    resolve_from_ref,
)


def git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.invalid")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "base.txt").write_text("base line\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def head(repo):
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def test_added_lines_yields_path_lineno_text(repo):
    base = head(repo)
    (repo / "new.txt").write_text("alpha\nbeta\n")
    (repo / "base.txt").write_text("base line\ngamma\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "change")
    got = list(added_lines(base, "HEAD"))
    assert ("new.txt", 1, "alpha") in got
    assert ("new.txt", 2, "beta") in got
    assert ("base.txt", 2, "gamma") in got
    assert all(not t.startswith("+") for _, _, t in got)


def test_added_or_renamed_paths_covers_A_and_R(repo):
    base = head(repo)
    (repo / "brand-new.md").write_text("x\n")
    git(repo, "add", ".")
    git(repo, "mv", "base.txt", "renamed.txt")
    git(repo, "commit", "-qm", "add+rename")
    got = added_or_renamed_paths(base, "HEAD")
    assert sorted(got) == ["brand-new.md", "renamed.txt"]


def test_resolve_from_ref_passthrough(repo):
    base = head(repo)
    assert resolve_from_ref(base, "origin/main") == base


def test_resolve_from_ref_zero_sha_falls_back_to_empty_tree(repo):
    # No origin/main exists in this fixture, so the merge-base fallback
    # fails and the empty tree (scan everything) is returned.
    assert resolve_from_ref(ZERO_SHA, "origin/main") == EMPTY_TREE
    assert resolve_from_ref(None, "origin/main") == EMPTY_TREE


def test_added_lines_from_empty_tree_scans_everything(repo):
    got = list(added_lines(EMPTY_TREE, "HEAD"))
    assert ("base.txt", 1, "base line") in got


def test_added_or_renamed_paths_from_empty_tree_lists_all_tracked(repo):
    assert added_or_renamed_paths(EMPTY_TREE, "HEAD") == ["base.txt"]


def test_non_ascii_path_is_returned_unescaped(repo):
    base = head(repo)
    (repo / "résumé.txt").write_text("alpha\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "unicode")
    assert added_or_renamed_paths(base, "HEAD") == ["résumé.txt"]
    assert ("résumé.txt", 1, "alpha") in list(added_lines(base, "HEAD"))


def test_path_with_spaces_has_no_trailing_tab(repo):
    base = head(repo)
    (repo / "space name.txt").write_text("alpha\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "space")
    assert ("space name.txt", 1, "alpha") in list(added_lines(base, "HEAD"))
