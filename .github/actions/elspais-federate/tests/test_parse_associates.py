import pytest

from parse_associates import parse_associates


def test_parses_simple_list():
    assert parse_associates("Cure-HHT/hht_admin\nCure-HHT/event_sourcing") == [
        "Cure-HHT/hht_admin",
        "Cure-HHT/event_sourcing",
    ]


def test_ignores_blanks_comments_and_whitespace():
    raw = "\n  Cure-HHT/hht_admin  \n\n# a comment\n\t\n"
    assert parse_associates(raw) == ["Cure-HHT/hht_admin"]


def test_deduplicates_preserving_order():
    raw = "Cure-HHT/b\nCure-HHT/a\nCure-HHT/b"
    assert parse_associates(raw) == ["Cure-HHT/b", "Cure-HHT/a"]


def test_empty_input_returns_empty_list():
    assert parse_associates("   \n\n") == []


@pytest.mark.parametrize(
    "bad",
    ["hht_admin", "Cure-HHT/hht_admin/extra", "Cure-HHT/", "/hht_admin", "Cure HHT/x"],
)
def test_rejects_malformed_entries(bad):
    with pytest.raises(ValueError) as excinfo:
        parse_associates(bad)
    assert bad.strip() in str(excinfo.value)
