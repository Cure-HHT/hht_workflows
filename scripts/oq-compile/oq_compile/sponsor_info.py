"""Resolve sponsor identity fields for the provenance sheet.

The sponsor's identity has exactly one home: ``sponsor-info.yaml``, sitting
beside the consuming repo's URS manifest and already read there by the URS
compile pipeline for its ``sponsor_name``, ``protocol_number`` and
``protocol_version`` keys. This module introduces no second place to declare
any of them -- it locates the file from the URS manifest path the OQ
manifest already resolves (for the URS-section column), so there is nothing
new for a consumer to keep in step.

A consumer with no URS manifest declared, no ``sponsor-info.yaml`` beside
it, or a file lacking a given key, gets no row for that key: each is
optional identity, resolved independently of the others, and the report is
still valid without any of them.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_SPONSOR_INFO_FILENAME = "sponsor-info.yaml"


def _load_sponsor_info(urs_manifest_path: Path | None) -> dict | None:
    """Load sponsor-info.yaml beside the URS manifest.

    Returns None whenever there is no URS manifest, no sponsor-info.yaml
    file beside it, or the file's top-level content is not a mapping.
    Shared by every ``resolve_*`` function below: they differ only in which
    key they read, not in how the file is located and parsed.
    """
    if urs_manifest_path is None:
        return None
    sponsor_info_path = Path(urs_manifest_path).parent / _SPONSOR_INFO_FILENAME
    if not sponsor_info_path.is_file():
        return None
    data = yaml.safe_load(sponsor_info_path.read_text())
    if not isinstance(data, dict):
        return None
    return data


def _resolve_string_field(urs_manifest_path: Path | None, key: str) -> str | None:
    """Read a single string key from sponsor-info.yaml, or None.

    Returns None -- never an empty string or a placeholder -- whenever the
    file is unreachable (see ``_load_sponsor_info``) or the key is absent,
    non-string, or blank.
    """
    data = _load_sponsor_info(urs_manifest_path)
    if data is None:
        return None
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def resolve_sponsor_name(urs_manifest_path: Path | None) -> str | None:
    """Read ``sponsor_name`` from sponsor-info.yaml beside the URS manifest.

    ``urs_manifest_path`` is the already-resolved path the caller used for
    URS-section lookup (or None when the consumer declares no URS manifest).
    """
    return _resolve_string_field(urs_manifest_path, "sponsor_name")


def resolve_protocol_number(urs_manifest_path: Path | None) -> str | None:
    """Read ``protocol_number`` from sponsor-info.yaml beside the URS
    manifest. Independent of ``protocol_version``: a file naming one but not
    the other yields a value for the one it names.
    """
    return _resolve_string_field(urs_manifest_path, "protocol_number")


def resolve_protocol_version(urs_manifest_path: Path | None) -> str | None:
    """Read ``protocol_version`` from sponsor-info.yaml beside the URS
    manifest. Independent of ``protocol_number``: a file naming one but not
    the other yields a value for the one it names.
    """
    return _resolve_string_field(urs_manifest_path, "protocol_version")
