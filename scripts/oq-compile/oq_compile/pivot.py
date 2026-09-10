"""Turn requirements-with-journeys into the two sheets, in both directions."""

from __future__ import annotations

from .load import Requirement
from .manifest import Manifest

PASS = "PASS"
FAIL = "FAIL"
NOT_RUN = "NOT RUN"

_FAIL_VERDICTS = frozenset({"fail", "failed", "failure", "error"})
_PASS_VERDICTS = frozenset({"pass", "passed", "success"})


def journey_verdict(verdict: str) -> str:
    """Render one journey's verdict.

    Anything that is neither a pass nor a fail — `unverified` above all — is
    NOT RUN. An absence of evidence is never reported as a failure: a
    premature red is worse than an honest blank.
    """
    lowered = (verdict or "").strip().lower()
    if lowered in _FAIL_VERDICTS:
        return FAIL
    if lowered in _PASS_VERDICTS:
        return PASS
    return NOT_RUN


def requirement_verdict(req: Requirement) -> str:
    """Roll a requirement's journeys up to one verdict.

    FAIL if any validating journey failed. PASS only when every assertion the
    requirement expects is verified — a partly-covered requirement has not
    been validated, whatever its journeys say. NOT RUN otherwise.
    """
    if any(journey_verdict(j.verdict) == FAIL for j in req.journeys):
        return FAIL
    if req.journeys and req.uat_verified_ratio >= 1.0:
        return PASS
    return NOT_RUN


def req_rows(reqs: tuple[Requirement, ...], manifest: Manifest) -> list[list[str]]:
    """One row per requirement: id, title, verdict, then one journey per column."""
    return [
        [r.id, r.title, requirement_verdict(r), *[j.id for j in r.journeys]]
        for r in sorted(reqs, key=lambda r: r.id)
    ]


def uat_rows(
    reqs: tuple[Requirement, ...],
    journey_titles: dict[str, str],
    manifest: Manifest,
) -> list[list[str]]:
    """One row per journey: case id, title, verdict, journey id, then one
    requirement per column.

    Membership is derived: a journey appears because it validates a
    requirement in scope. A journey validating nothing in scope has no
    traceability to report and no row here.
    """
    validated: dict[str, list[str]] = {}
    verdicts: dict[str, str] = {}
    for req in sorted(reqs, key=lambda r: r.id):
        for ref in req.journeys:
            validated.setdefault(ref.id, []).append(req.id)
            verdicts.setdefault(ref.id, ref.verdict)

    return [
        [
            f"{manifest.uat_case_prefix}{jid}",
            journey_titles.get(jid, ""),
            journey_verdict(verdicts[jid]),
            jid,
            *validated[jid],
        ]
        for jid in sorted(validated)
    ]
