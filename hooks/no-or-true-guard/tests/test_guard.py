import textwrap

from no_or_true_guard.__main__ import main, scan


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(textwrap.dedent(content))
    return str(path)


def test_detects_bare_or_true(tmp_path):
    f = _write(tmp_path, "a.sh", "kill \"$PID\" 2>/dev/null || true\n")
    violations = scan([f])
    assert len(violations) == 1
    assert violations[0][0] == f
    assert violations[0][1] == 1


def test_detects_or_colon(tmp_path):
    f = _write(tmp_path, "a.sh", "cmd || :\n")
    violations = scan([f])
    assert len(violations) == 1


def test_detects_inside_command_substitution(tmp_path):
    f = _write(tmp_path, "a.sh", "VAR=$(cmd | grep pattern || true)\n")
    violations = scan([f])
    assert len(violations) == 1


def test_ignores_clean_file(tmp_path):
    f = _write(
        tmp_path,
        "a.sh",
        """\
        VAR="$(cmd)" || VAR=""
        if ! cmd; then
          echo "::warning::tolerated"
        fi
        """,
    )
    violations = scan([f])
    assert violations == []


def test_multiple_files_multiple_violations(tmp_path):
    f1 = _write(tmp_path, "a.sh", "cmd || true\n")
    f2 = _write(tmp_path, "b.yml", "run: cmd || true\n")
    violations = scan([f1, f2])
    assert len(violations) == 2


def test_main_returns_zero_when_no_violations(tmp_path):
    f = _write(tmp_path, "a.sh", "echo hi\n")
    assert main([f]) == 0


def test_main_returns_one_and_prints_when_violations(tmp_path, capsys):
    f = _write(tmp_path, "a.sh", "cmd || true\n")
    assert main([f]) == 1
    out = capsys.readouterr().out
    assert "no-or-true-guard" in out
    assert f in out


def test_unreadable_file_is_treated_as_violation(tmp_path, capsys):
    # A directory path raises IsADirectoryError (an OSError subclass) when
    # opened for reading — fail-closed instead of silently skipping it.
    unreadable = tmp_path / "a_directory"
    unreadable.mkdir()
    violations = scan([str(unreadable)])
    assert len(violations) == 1
    assert violations[0][0] == str(unreadable)
    err = capsys.readouterr().err
    assert "could not read" in err
    assert str(unreadable) in err
