import subprocess

import pytest

from confidential_terms_scan.__main__ import main


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
    base = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    monkeypatch.chdir(tmp_path)
    for var in (
        "CONFIDENTIAL_PROHIBIT_LIST", "PRE_COMMIT_FROM_REF", "PRE_COMMIT_TO_REF",
        "PRE_COMMIT_REMOTE_BRANCH", "BRANCH_NAME", "PR_TITLE", "PR_BODY",
    ):
        monkeypatch.delenv(var, raising=False)
    return tmp_path, base


def commit_zebra_file(repo_path):
    (repo_path / "notes.md").write_text("a zebra appears\n")
    git(repo_path, "add", ".")
    git(repo_path, "commit", "-qm", "notes")


def test_missing_list_and_no_doppler_project_is_config_error(repo, capsys):
    _, base = repo
    assert main(["--from-ref", base]) == 2
    err = capsys.readouterr().err
    assert "CONFIDENTIAL_PROHIBIT_LIST" in err


def test_empty_list_is_clean_noop(repo, monkeypatch, capsys):
    _, base = repo
    monkeypatch.setenv("CONFIDENTIAL_PROHIBIT_LIST", "")
    assert main(["--from-ref", base]) == 0
    assert "empty" in capsys.readouterr().out


def test_content_finding_fails_without_echoing_term(repo, monkeypatch, capsys):
    repo_path, base = repo
    commit_zebra_file(repo_path)
    monkeypatch.setenv("CONFIDENTIAL_PROHIBIT_LIST", "zebra")
    assert main(["--from-ref", base]) == 1
    err = capsys.readouterr().err
    assert "notes.md:1" in err
    assert "zebra" not in err


def test_metadata_finding_reports_field_name_only(repo, monkeypatch, capsys):
    _, base = repo
    monkeypatch.setenv("CONFIDENTIAL_PROHIBIT_LIST", "zebra")
    monkeypatch.setenv("PR_TITLE", "introduce zebra support")
    assert main(["--from-ref", base]) == 1
    err = capsys.readouterr().err
    assert "pr-title" in err
    assert "zebra" not in err


def test_branch_name_from_pre_commit_remote_branch(repo, monkeypatch, capsys):
    _, base = repo
    monkeypatch.setenv("CONFIDENTIAL_PROHIBIT_LIST", "zebra")
    monkeypatch.setenv("PRE_COMMIT_REMOTE_BRANCH", "refs/heads/feat/zebra-x")
    assert main(["--from-ref", base]) == 1
    err = capsys.readouterr().err
    assert "branch-name" in err
    assert "zebra" not in err


def test_allow_file_suppresses_path_and_content(repo, monkeypatch):
    repo_path, base = repo
    commit_zebra_file(repo_path)
    (repo_path / ".confidential-terms-allow").write_text("notes.md\n")
    monkeypatch.setenv("CONFIDENTIAL_PROHIBIT_LIST", "zebra")
    assert main(["--from-ref", base]) == 0


def test_clean_range_passes(repo, monkeypatch, capsys):
    repo_path, base = repo
    (repo_path / "clean.md").write_text("nothing here\n")
    git(repo_path, "add", ".")
    git(repo_path, "commit", "-qm", "clean")
    monkeypatch.setenv("CONFIDENTIAL_PROHIBIT_LIST", "zebra")
    assert main(["--from-ref", base]) == 0
    assert "PASS" in capsys.readouterr().out
