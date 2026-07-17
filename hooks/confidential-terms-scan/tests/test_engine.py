"""Engine tests. All terms here are synthetic fixtures (zebra, acme-x);
real terms never appear in this repo."""
from confidential_terms_scan.engine import (
    MASK,
    build_pattern,
    is_allowed,
    load_allow_globs,
    mask_path,
    parse_prohibit_list,
    scan_content_lines,
    scan_metadata,
    scan_paths,
)


def test_parse_strips_and_drops_empties():
    assert parse_prohibit_list(" zebra , acme-x ,, ") == ["zebra", "acme-x"]


def test_parse_empty_and_blank_give_no_terms():
    assert parse_prohibit_list("") == []
    assert parse_prohibit_list("  ") == []


def test_build_pattern_none_when_no_terms():
    assert build_pattern([]) is None


def test_pattern_is_word_boundary_and_case_insensitive():
    p = build_pattern(["zebra"])
    assert p.search("a ZEBRA here")
    assert not p.search("zebrafish")
    assert not p.search("subzebra")


def test_pattern_escapes_metacharacters():
    p = build_pattern(["a.b"])
    assert p.search("x a.b y")
    assert not p.search("x aXb y")


def test_hyphenated_term_matches_at_plain_word_boundaries():
    p = build_pattern(["acme-x"])
    assert p.search("the acme-x build")
    assert p.search("The ACME-X tool")
    assert not p.search("macme-x")
    assert not p.search("acme-x1")  # \b: no boundary inside a longer token


def test_scan_content_lines_reports_location_never_text():
    p = build_pattern(["zebra"])
    lines = [("src/a.py", 3, "the zebra line"), ("src/a.py", 4, "clean")]
    assert scan_content_lines(p, lines) == [("content", "src/a.py:3")]


def test_mask_path_masks_only_matching_segments():
    p = build_pattern(["zebra"])
    assert mask_path("docs/zebra/notes.md", p) == ("docs/%s/notes.md" % MASK, True)
    assert mask_path("docs/clean/notes.md", p) == ("docs/clean/notes.md", False)


def test_scan_paths_classifies_basename_vs_segment():
    p = build_pattern(["zebra"])
    assert scan_paths(p, ["a/zebra.md"]) == [("filename", "a/%s" % MASK)]
    assert scan_paths(p, ["zebra/b.md"]) == [("path-segment", "%s/b.md" % MASK)]
    assert scan_paths(p, ["a/clean.md"]) == []


def test_scan_metadata_reports_field_names_only():
    p = build_pattern(["zebra"])
    fields = {"pr-title": "add zebra", "pr-body": "", "branch-name": "feat/clean"}
    assert scan_metadata(p, fields) == [("metadata", "pr-title")]


def test_allow_globs_parse_and_match():
    globs = load_allow_globs("# comment\n\ndocs/legal/*.md\n")
    assert globs == ["docs/legal/*.md"]
    assert is_allowed("docs/legal/terms.md", globs)
    assert not is_allowed("src/a.py", globs)
