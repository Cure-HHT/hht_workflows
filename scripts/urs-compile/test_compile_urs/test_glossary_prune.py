"""Tests for glossary/references pruning of unreferenced terms."""

import importlib.util
from pathlib import Path


def _mod():
    spec_path = Path(__file__).parents[1] / "compile-urs.py"
    spec = importlib.util.spec_from_file_location("compile_urs", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GLOSSARY = """\
<!-- Auto-generated -->
# Glossary

## A

**Action**
: A discrete operation.
*Defined in: DIARY-PRD-action-inventory (DIARY)*

**Audit Trail**
: The immutable log.
*Defined in: file:spec/glossary-core.md (DIARY)*

## C

**CRA (Clinical Research Associate)**
: A monitor role.
*Defined in: file:spec/glossary-core.md (DIARY)*

## E

**Event Store**
: Append-only event log.
*Defined in: file:spec/glossary-core.md (DIARY)*

# References

**FDA 21 CFR Part 11 (Regulation)**
: Electronic Records; Electronic Signatures
*Defined in: file:spec/glossary-core.md (DIARY)*
"""


def test_keeps_only_referenced_terms():
    mod = _mod()
    body = "The **Action** is gated by RBAC. The **CRA** reviews the audit log."
    out = mod.prune_glossary_terms(GLOSSARY, body)
    assert "**Action**" in out                       # referenced
    assert "**CRA (Clinical Research Associate)**" in out  # acronym -> body "CRA"
    assert "**Audit Trail**" not in out              # not referenced (only "audit log")
    assert "**Event Store**" not in out              # DEV-only term


def test_drops_empty_letter_headings_keeps_populated():
    mod = _mod()
    body = "The **Action** happens."
    out = mod.prune_glossary_terms(GLOSSARY, body)
    assert "## A" in out          # has Action
    assert "## C" not in out      # CRA dropped -> empty
    assert "## E" not in out      # Event Store dropped -> empty


def test_drops_empty_references_section():
    mod = _mod()
    body = "The **Action** happens."  # no reference cited
    out = mod.prune_glossary_terms(GLOSSARY, body)
    assert "# References" not in out
    assert "FDA 21 CFR Part 11" not in out


def test_keeps_references_section_when_cited():
    mod = _mod()
    body = "Compliant with **FDA 21 CFR Part 11**."
    out = mod.prune_glossary_terms(GLOSSARY, body)
    assert "# References" in out
    assert "**FDA 21 CFR Part 11 (Regulation)**" in out


def test_glossary_h1_always_kept():
    mod = _mod()
    out = mod.prune_glossary_terms(GLOSSARY, "nothing referenced here")
    assert "# Glossary" in out


def test_plural_and_possessive_count_as_reference():
    mod = _mod()
    assert mod._is_term_referenced("Action", "many actions occur")
    assert mod._is_term_referenced("Participant", "the participant's device")
    assert not mod._is_term_referenced("Site", "website content")  # word-bounded


def test_multiword_parenthetical_alias_but_not_type_tag():
    mod = _mod()
    # spelled-out expansion counts
    assert mod._is_term_referenced(
        "CRA (Clinical Research Associate)", "a clinical research associate monitors"
    )
    # single-word type tag must NOT cause a keep on its own
    assert not mod._is_term_referenced(
        "FDA 21 CFR Part 11 (Regulation)", "this regulation applies"
    )
