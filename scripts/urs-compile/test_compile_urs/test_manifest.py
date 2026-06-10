import pytest

from urs_compile.manifest import Manifest, Section, Chapter


def test_load_from_dict(sample_manifest_dict):
    m = Manifest.from_dict(sample_manifest_dict)
    assert m.document["title"] == "Test URS"
    assert len(m.chapters) == 2


def test_chapter_has_sections(sample_manifest_dict):
    m = Manifest.from_dict(sample_manifest_dict)
    ch = m.chapters[0]
    assert ch.number == 4
    assert ch.title == "SYSTEM-WIDE STANDARDS"
    assert len(ch.sections) == 1


def test_chapter_scope_defaults_core(sample_manifest_dict):
    m = Manifest.from_dict(sample_manifest_dict)
    assert m.chapters[0].scope == "core"
    assert m.chapters[1].scope == "sponsor"


def test_chapter_scope_rejects_unknown_value():
    with pytest.raises(ValueError, match="scope"):
        Manifest.from_dict({
            "chapters": [{"number": 4, "title": "X", "sections": [],
                          "scope": "bogus"}],
        })


def test_section_has_files(sample_manifest_dict):
    m = Manifest.from_dict(sample_manifest_dict)
    sec = m.chapters[0].sections[0]
    assert sec.number == "4.3"
    assert sec.files == ["spec/prd-rbac.md"]


def test_validation_rejects_missing_required_field():
    with pytest.raises(ValueError, match="number"):
        Manifest.from_dict({"chapters": [{"title": "X", "sections": []}]})


def test_term_index_field():
    m = Manifest.from_dict({
        "chapters": [],
        "term_index": "spec/_generated/term-index.md",
    })
    assert m.term_index == "spec/_generated/term-index.md"


def test_term_index_defaults_none(sample_manifest_dict):
    m = Manifest.from_dict(sample_manifest_dict)
    assert m.term_index is None
