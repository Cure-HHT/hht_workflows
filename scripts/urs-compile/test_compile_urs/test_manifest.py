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


# --- levels ---

def test_levels_default_prd_gui(sample_manifest_dict):
    assert Manifest.from_dict(sample_manifest_dict).levels == ("PRD", "GUI")


def test_levels_explicit_list():
    m = Manifest.from_dict({"document": {}, "levels": ["BASE", "OPS", "DEV"], "chapters": []})
    assert m.levels == ("BASE", "OPS", "DEV")


# --- metadata_fields ---

def test_metadata_default_empty(sample_manifest_dict):
    assert Manifest.from_dict(sample_manifest_dict).metadata_fields == ()


def test_metadata_false_empty():
    assert Manifest.from_dict({"document": {}, "metadata": False, "chapters": []}).metadata_fields == ()


def test_metadata_true_means_all_fields():
    assert Manifest.from_dict({"document": {}, "metadata": True, "chapters": []}).metadata_fields == ("level", "status", "hash")


def test_metadata_explicit_field_list():
    assert Manifest.from_dict({"document": {}, "metadata": ["level", "status"], "chapters": []}).metadata_fields == ("level", "status")


def test_metadata_rejects_unknown_field():
    with pytest.raises(ValueError, match="metadata"):
        Manifest.from_dict({"document": {}, "metadata": ["bogus"], "chapters": []})


# --- section levels ---

def test_section_levels_default_none(sample_manifest_dict):
    m = Manifest.from_dict(sample_manifest_dict)
    assert m.chapters[0].sections[0].levels is None


def test_section_levels_explicit():
    m = Manifest.from_dict({"document": {}, "chapters": [
        {"number": 9, "title": "Development", "sections": [
            {"number": "9.1", "title": "All DEV", "levels": ["DEV"]}]}]})
    assert m.chapters[0].sections[0].levels == ("DEV",)
    assert m.chapters[0].sections[0].files == []


# --- input validation (Copilot review): fail loud on malformed YAML types ---

def test_levels_rejects_non_list_scalar():
    with pytest.raises(ValueError, match="levels"):
        Manifest.from_dict({"document": {}, "levels": "DEV", "chapters": []})


def test_section_levels_rejects_non_list_scalar():
    with pytest.raises(ValueError, match="levels"):
        Manifest.from_dict({"document": {}, "chapters": [
            {"number": 9, "title": "X", "sections": [
                {"number": "9.1", "title": "S", "levels": "DEV"}]}]})


def test_metadata_rejects_non_list_non_bool_scalar():
    with pytest.raises(ValueError, match="metadata"):
        Manifest.from_dict({"document": {}, "metadata": "level", "chapters": []})
