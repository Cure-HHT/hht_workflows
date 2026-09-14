"""Offline unit tests for the obtain-upstream action's materialisation stamp.

The stamp is what makes a repeat request a no-op. A run that needs an upstream
in five steps should materialise it once, and the only way a later step can
know the tree already holds the commit it wants is to read what the earlier one
recorded.

The whitespace case is not fussiness. The action writes the stamp with a
trailing newline so the file is well-formed, and a reader that compares the raw
bytes against a bare sha would find them unequal and copy the tree again --
silently correct, silently wasteful, and a second materialisation of something
that was supposed to exist once.
"""

import pathlib

from stamp import read_stamp, write_stamp

GOOD = "cbbbf10438edc6c2d83e8d0efbee4b32ced4feae"


def test_absent_stamp_reads_as_none(tmp_path):
    assert read_stamp(str(tmp_path)) is None


def test_written_stamp_reads_back(tmp_path):
    write_stamp(str(tmp_path), GOOD)
    assert read_stamp(str(tmp_path)) == GOOD


def test_stamp_of_a_different_commit_does_not_match(tmp_path):
    write_stamp(str(tmp_path), GOOD)
    assert read_stamp(str(tmp_path)) != "0" * 40


def test_trailing_whitespace_is_not_part_of_the_stamp(tmp_path):
    pathlib.Path(tmp_path, ".upstream-commit").write_text(GOOD + "\n")
    assert read_stamp(str(tmp_path)) == GOOD


def test_writing_creates_the_directory_if_absent(tmp_path):
    dest = tmp_path / "not-yet-there"
    write_stamp(str(dest), GOOD)
    assert read_stamp(str(dest)) == GOOD
