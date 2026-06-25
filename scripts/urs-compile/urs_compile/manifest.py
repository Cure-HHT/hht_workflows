"""Load and validate tools/urs-section-map.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Section:
    number: str
    title: str
    files: list[str]
    levels: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Chapter:
    number: int
    title: str
    sections: list[Section]
    # Optional path (repo-relative) to a markdown file holding the
    # chapter-level intro prose that renders between the chapter heading
    # and its first section. Separates spec-author prose work from
    # manifest / pipeline edits — the file is plain markdown, no
    # frontmatter or scripting required.
    intro_file: str | None = None
    # Which REQ namespace the chapter emits: "core" (DIARY-*) or
    # "sponsor" (everything else). Sponsor-overlay REQs are collected
    # into their own chapter instead of interleaving with core REQs.
    scope: str = "core"


@dataclass(frozen=True)
class Manifest:
    document: dict[str, Any]
    frontmatter: str | None
    appendices: str | None
    glossary: str | None
    term_index: str | None
    chapters: list[Chapter]
    # When True, glossary and references entries whose term is not
    # referenced anywhere in the assembled document body are dropped.
    # The federated glossary aggregates every defined term across all
    # repos (core glossary, DEV/OPS specs) — many of which never appear
    # in this PRD/GUI-only deliverable. Default on so the URS glossary
    # is self-contained.
    prune_glossary: bool = True
    # Requirement levels included in this document, in presentation order.
    # Default matches the historical PRD/GUI-only URS deliverable.
    levels: tuple[str, ...] = ("PRD", "GUI")
    # Which REQ-node content fields to render alongside each requirement.
    # Empty tuple = no metadata shown (default). Valid field names:
    # "level", "status", "hash".
    metadata_fields: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Manifest":
        chapters: list[Chapter] = []
        for ch in d.get("chapters", []):
            if "number" not in ch:
                raise ValueError(f"chapter missing 'number': {ch}")
            sections = [
                Section(
                    number=s["number"],
                    title=s["title"],
                    files=list(s.get("files", [])),
                    levels=tuple(s["levels"]) if s.get("levels") else None,
                )
                for s in ch.get("sections", [])
            ]
            scope = ch.get("scope", "core")
            if scope not in ("core", "sponsor"):
                raise ValueError(
                    f"chapter {ch['number']}: scope must be 'core' or "
                    f"'sponsor', got {scope!r}"
                )
            chapters.append(Chapter(
                number=int(ch["number"]),
                title=ch["title"],
                sections=sections,
                intro_file=ch.get("intro_file"),
                scope=scope,
            ))
        levels = tuple(d.get("levels") or ("PRD", "GUI"))

        _VALID_METADATA_FIELDS = ("level", "status", "hash")
        _raw_metadata = d.get("metadata")
        if not _raw_metadata:
            metadata_fields: tuple[str, ...] = ()
        elif _raw_metadata is True:
            metadata_fields = _VALID_METADATA_FIELDS
        else:
            for _field in _raw_metadata:
                if _field not in _VALID_METADATA_FIELDS:
                    raise ValueError(
                        f"metadata: unknown field {_field!r}; "
                        f"valid fields are {list(_VALID_METADATA_FIELDS)}"
                    )
            metadata_fields = tuple(_raw_metadata)

        return cls(
            document=d.get("document", {}),
            frontmatter=d.get("frontmatter"),
            appendices=d.get("appendices"),
            glossary=d.get("glossary"),
            term_index=d.get("term_index"),
            chapters=chapters,
            prune_glossary=bool(d.get("prune_glossary", True)),
            levels=levels,
            metadata_fields=metadata_fields,
        )

    @classmethod
    def from_yaml_path(cls, path: Path) -> "Manifest":
        return cls.from_dict(yaml.safe_load(path.read_text()))
