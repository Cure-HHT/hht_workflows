"""End-to-end integration tests for the release-notes-update hook."""
import os
import subprocess
from pathlib import Path

from release_notes_update.__main__ import main


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "-C", str(repo), "init", "-q", "-b", "main"])
    subprocess.check_call(["git", "-C", str(repo), "config", "user.email", "t@t"])
    subprocess.check_call(["git", "-C", str(repo), "config", "user.name", "t"])
    subprocess.check_call(["git", "-C", str(repo), "config", "commit.gpgsign", "false"])


def _commit(repo: Path, file: str, content: str, message: str) -> None:
    (repo / file).write_text(content)
    subprocess.check_call(["git", "-C", str(repo), "add", file])
    subprocess.check_call(["git", "-C", str(repo), "commit", "-q", "-m", message])


def test_first_run_creates_notes_and_fragment(tmp_path, monkeypatch):
    repo = tmp_path / "consumer"
    _init_repo(repo)
    _commit(repo, "VERSION", "v1.0.0+1", "initial")
    subprocess.check_call(["git", "-C", str(repo), "branch", "origin/main"])
    subprocess.check_call(["git", "-C", str(repo), "checkout", "-q", "-b", "feat/foo"])
    _commit(repo, "code.txt", "hello", "[CUR-42] add feature")

    monkeypatch.chdir(repo)
    rc = main(["--version-command", "cat VERSION"])
    assert rc == 0

    fragment_path = repo / ".release-notes" / "feat-foo.md"
    assert fragment_path.exists()
    text = fragment_path.read_text()
    assert "<!-- version: v1.0.0+1 -->" in text
    assert "- [CUR-42] add feature" in text


def test_consolidates_pending_origin_fragment(tmp_path, monkeypatch):
    repo = tmp_path / "consumer"
    _init_repo(repo)
    _commit(repo, "VERSION", "v1.0.0+1", "initial")
    # Simulate a previous PR's fragment present on main.
    frag_dir = repo / ".release-notes"
    frag_dir.mkdir()
    (frag_dir / "old-pr.md").write_text(
        "<!-- release-notes-fragment v1 -->\n"
        "<!-- version: v1.0.0+1 -->\n"
        "\n"
        "- [CUR-1] previous PR contribution\n"
    )
    subprocess.check_call(["git", "-C", str(repo), "add", "."])
    subprocess.check_call(["git", "-C", str(repo), "commit", "-q", "-m", "[CUR-1] previous"])
    subprocess.check_call(["git", "-C", str(repo), "branch", "origin/main"])
    subprocess.check_call(["git", "-C", str(repo), "checkout", "-q", "-b", "feat/bar"])
    _commit(repo, "x.txt", "x", "[CUR-99] new work")

    monkeypatch.chdir(repo)
    rc = main(["--version-command", "cat VERSION"])
    assert rc == 0

    notes = (repo / "RELEASE_NOTES.md").read_text()
    assert "## v1.0.0+1" in notes
    assert "- [CUR-1] previous PR contribution" in notes
    # The old fragment should have been removed from disk.
    assert not (frag_dir / "old-pr.md").exists()
    # New PR's fragment should still exist (it hasn't merged yet).
    assert (frag_dir / "feat-bar.md").exists()


def test_staleness_guard_errors(tmp_path, monkeypatch):
    repo = tmp_path / "consumer"
    _init_repo(repo)
    _commit(repo, "VERSION", "v1.0.0+1", "initial")
    # Pre-populate RELEASE_NOTES.md with a NEWER version section than VERSION.
    (repo / "RELEASE_NOTES.md").write_text(
        "# Release Notes\n\n"
        "## v2.0.0+1 — 2026-06-01\n\n"
        "<!-- summary -->\n<!-- /summary -->\n\n"
        "<!-- entries -->\n- [CUR-1] newer release\n<!-- /entries -->\n"
    )
    subprocess.check_call(["git", "-C", str(repo), "add", "."])
    subprocess.check_call(["git", "-C", str(repo), "commit", "-q", "-m", "[CUR-1] setup"])
    subprocess.check_call(["git", "-C", str(repo), "branch", "origin/main"])
    subprocess.check_call(["git", "-C", str(repo), "checkout", "-q", "-b", "feat/baz"])
    _commit(repo, "y.txt", "y", "[CUR-2] work")

    monkeypatch.chdir(repo)
    rc = main(["--version-command", "cat VERSION"])
    assert rc != 0  # should fail with staleness error
