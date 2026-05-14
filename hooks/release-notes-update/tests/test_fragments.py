"""Tests for fragments module."""
from pathlib import Path

import pytest

from release_notes_update.fragments import (
    Fragment,
    append_bullets,
    fragment_from_commits,
    parse_fragment,
    parse_fragments,
    read_fragments_dir,
    render_fragment,
)


def test_fragment_from_commits_keeps_only_cur_prefixed():
    commits = [
        "[CUR-123] First change",
        "fixup",
        "[CUR-456] Second change",
        "WIP",
    ]
    frag = fragment_from_commits(commits, version="v1.2.3+5")
    assert frag.version == "v1.2.3+5"
    assert frag.bullets == (
        "[CUR-123] First change",
        "[CUR-456] Second change",
    )


def test_fragment_from_commits_empty_when_no_prefix():
    frag = fragment_from_commits(["fixup", "WIP"], version="v1.0.0+1")
    assert frag.bullets == ()


def test_render_fragment_roundtrip():
    frag = Fragment(
        version="v1.2.3+5",
        bullets=["[CUR-123] First change", "[CUR-456] Second change"],
    )
    rendered = render_fragment(frag)
    parsed = parse_fragment(rendered)
    assert parsed == frag


def test_parse_fragment_rejects_unknown_format():
    with pytest.raises(ValueError, match="unknown fragment format"):
        parse_fragment("not a fragment\n")


def test_render_fragment_format():
    frag = Fragment(version="v1.0.0+1", bullets=["[CUR-1] foo"])
    rendered = render_fragment(frag)
    assert rendered.startswith("<!-- release-notes-fragment v1 -->\n")
    assert "<!-- version: v1.0.0+1 -->\n" in rendered
    assert "- [CUR-1] foo\n" in rendered


def test_parse_fragments_skips_malformed(capsys):
    source = [
        ("a.md", "<!-- release-notes-fragment v1 -->\n<!-- version: v1 -->\n- [CUR-1] ok"),
        ("b.md", "garbage"),
        ("c.md", "<!-- release-notes-fragment v1 -->\n<!-- version: v2 -->\n- [CUR-2] ok"),
    ]
    parsed = list(parse_fragments(source))
    assert [ident for ident, _ in parsed] == ["a.md", "c.md"]
    err = capsys.readouterr().err
    assert "b.md" in err


def test_read_fragments_dir_yields_md_files_only(tmp_path):
    (tmp_path / "ok.md").write_text("content of ok\n")
    (tmp_path / "ignored.txt").write_text("not markdown\n")
    (tmp_path / "subdir").mkdir()
    out = list(read_fragments_dir(tmp_path))
    assert [p.name for p, _ in out] == ["ok.md"]
    assert out[0][1] == "content of ok\n"


def test_read_fragments_dir_returns_empty_when_dir_absent(tmp_path):
    out = list(read_fragments_dir(tmp_path / "does-not-exist"))
    assert out == []


def test_append_bullets_dedupes_against_existing():
    entries = ("- [CUR-1] foo", "- [CUR-2] bar")
    result = append_bullets(entries, ["[CUR-1] foo", "[CUR-3] baz"])
    assert result == ("- [CUR-1] foo", "- [CUR-2] bar", "- [CUR-3] baz")


def test_append_bullets_dedupes_within_new_batch():
    entries = ()
    result = append_bullets(entries, ["[CUR-1] foo", "[CUR-1] foo"])
    assert result == ("- [CUR-1] foo",)
