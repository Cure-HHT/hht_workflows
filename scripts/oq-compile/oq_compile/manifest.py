"""Load and validate the sponsor-supplied OQ manifest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_UAT_PREFIX = "UAT-"
_DEFAULT_PROVENANCE_NAME = "Provenance"


def _require(mapping: dict[str, Any], key: str, ctx: str) -> Any:
    """Return ``mapping[key]``, or fail loud naming ``ctx``."""
    if key not in mapping or mapping[key] is None:
        raise ValueError(f"{ctx}: required key '{key}' is missing")
    return mapping[key]


def _coerce_columns(raw: Any, ctx: str) -> tuple[str, ...]:
    """Validate a ``columns:`` value and return it as a tuple.

    A ``columns:`` written as a bare scalar would otherwise be silently
    turned into a tuple of characters that names no column; require a list
    of strings and fail loud, naming ``ctx``.
    """
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise ValueError(f"{ctx}: 'columns' must be a list of strings, got {raw!r}")
    return tuple(raw)


@dataclass(frozen=True)
class SheetSpec:
    name: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class Manifest:
    title: str
    project: str
    scope: str
    uat_case_prefix: str
    req_sheet: SheetSpec
    uat_sheet: SheetSpec
    provenance_sheet_name: str

    @classmethod
    def from_path(cls, path: Path) -> Manifest:
        raw = yaml.safe_load(Path(path).read_text())
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: manifest must be a mapping, got {type(raw).__name__}")

        document = _require(raw, "document", str(path))
        sheets = _require(raw, "sheets", str(path))

        def sheet(key: str, default_name: str) -> SheetSpec:
            spec = _require(sheets, key, f"{path}: sheets")
            return SheetSpec(
                name=str(spec.get("name", default_name)),
                columns=_coerce_columns(
                    _require(spec, "columns", f"{path}: sheets.{key}"),
                    f"{path}: sheets.{key}",
                ),
            )

        provenance = sheets.get("provenance") or {}
        return cls(
            title=str(_require(document, "title", f"{path}: document")),
            project=str(_require(document, "project", f"{path}: document")),
            scope=str(_require(raw, "scope", str(path))),
            uat_case_prefix=str(raw.get("uat_case_prefix", _DEFAULT_UAT_PREFIX)),
            req_sheet=sheet("req", "REQ"),
            uat_sheet=sheet("uat", "UAT Test Cases"),
            provenance_sheet_name=str(
                provenance.get("name", _DEFAULT_PROVENANCE_NAME)
            ),
        )
