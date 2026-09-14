"""resolve_sponsor_name / resolve_protocol_number / resolve_protocol_version:
each row's only source of truth.

sponsor-info.yaml sits beside the consuming repo's URS manifest and is
already read by the URS compile pipeline for the same keys -- this module
introduces no second place to declare any of them, and no manifest key of
its own names its path. Each key is resolved independently of the others.
"""

from __future__ import annotations

from oq_compile.sponsor_info import (
    resolve_protocol_number,
    resolve_protocol_version,
    resolve_sponsor_name,
)


def test_no_urs_manifest_path_yields_no_sponsor(tmp_path):
    # A consumer that declares no urs_manifest in its OQ manifest has no
    # known place to look for sponsor-info.yaml at all.
    assert resolve_sponsor_name(None) is None


def test_no_sponsor_info_file_beside_the_urs_manifest_yields_no_sponsor(tmp_path):
    urs = tmp_path / "spec" / "URS-manifest" / "urs.yaml"
    urs.parent.mkdir(parents=True)
    urs.write_text("document: {}\n")
    assert resolve_sponsor_name(urs) is None


def test_sponsor_info_present_but_missing_the_key_yields_no_sponsor(tmp_path):
    urs = tmp_path / "spec" / "URS-manifest" / "urs.yaml"
    urs.parent.mkdir(parents=True)
    urs.write_text("document: {}\n")
    (urs.parent / "sponsor-info.yaml").write_text("protocol_number: EXAMPLE-0001\n")
    assert resolve_sponsor_name(urs) is None


def test_sponsor_info_with_an_empty_name_yields_no_sponsor(tmp_path):
    urs = tmp_path / "spec" / "URS-manifest" / "urs.yaml"
    urs.parent.mkdir(parents=True)
    urs.write_text("document: {}\n")
    (urs.parent / "sponsor-info.yaml").write_text("sponsor_name: ''\n")
    assert resolve_sponsor_name(urs) is None


def test_sponsor_name_is_read_verbatim_from_the_file(tmp_path):
    urs = tmp_path / "spec" / "URS-manifest" / "urs.yaml"
    urs.parent.mkdir(parents=True)
    urs.write_text("document: {}\n")
    (urs.parent / "sponsor-info.yaml").write_text(
        "sponsor_name: Example Sponsor, Inc.\n"
    )
    assert resolve_sponsor_name(urs) == "Example Sponsor, Inc."


def test_no_urs_manifest_path_yields_no_protocol_number_or_version(tmp_path):
    assert resolve_protocol_number(None) is None
    assert resolve_protocol_version(None) is None


def test_no_sponsor_info_file_yields_no_protocol_number_or_version(tmp_path):
    urs = tmp_path / "spec" / "URS-manifest" / "urs.yaml"
    urs.parent.mkdir(parents=True)
    urs.write_text("document: {}\n")
    assert resolve_protocol_number(urs) is None
    assert resolve_protocol_version(urs) is None


def test_protocol_number_and_version_are_each_independently_resolved(tmp_path):
    """A file naming only one of the two keys yields a value for that one
    and None for the other -- neither key implies the other."""
    urs = tmp_path / "spec" / "URS-manifest" / "urs.yaml"
    urs.parent.mkdir(parents=True)
    urs.write_text("document: {}\n")
    (urs.parent / "sponsor-info.yaml").write_text("protocol_number: EXAMPLE-0001\n")
    assert resolve_protocol_number(urs) == "EXAMPLE-0001"
    assert resolve_protocol_version(urs) is None

    (urs.parent / "sponsor-info.yaml").write_text("protocol_version: '3.0'\n")
    assert resolve_protocol_number(urs) is None
    assert resolve_protocol_version(urs) == "3.0"


def test_protocol_number_and_version_are_read_verbatim_when_both_present(tmp_path):
    urs = tmp_path / "spec" / "URS-manifest" / "urs.yaml"
    urs.parent.mkdir(parents=True)
    urs.write_text("document: {}\n")
    (urs.parent / "sponsor-info.yaml").write_text(
        "protocol_number: EXAMPLE-0001\nprotocol_version: '3.0'\n"
    )
    assert resolve_protocol_number(urs) == "EXAMPLE-0001"
    assert resolve_protocol_version(urs) == "3.0"


def test_empty_protocol_number_or_version_yields_no_value(tmp_path):
    urs = tmp_path / "spec" / "URS-manifest" / "urs.yaml"
    urs.parent.mkdir(parents=True)
    urs.write_text("document: {}\n")
    (urs.parent / "sponsor-info.yaml").write_text(
        "protocol_number: ''\nprotocol_version: ''\n"
    )
    assert resolve_protocol_number(urs) is None
    assert resolve_protocol_version(urs) is None
