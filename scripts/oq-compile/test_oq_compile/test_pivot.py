from __future__ import annotations

from oq_compile.load import JourneyRef, Requirement, load_journeys, load_trace
from oq_compile.manifest import Manifest
from oq_compile.pivot import (
    FAIL,
    NOT_RUN,
    PASS,
    req_rows,
    requirement_verdict,
    uat_rows,
)


def _req(rid, ratio, journeys):
    return Requirement(
        id=rid, title=rid.title(), level="PRD", status="Draft",
        uat_verified_ratio=ratio, journeys=tuple(journeys),
    )


def test_verdict_pass_when_fully_verified():
    r = _req("SPN-PRD-a", 1.0, [JourneyRef("JNY-1", "pass")])
    assert requirement_verdict(r) == PASS


def test_verdict_fail_when_any_journey_failed():
    r = _req("SPN-PRD-a", 1.0, [JourneyRef("JNY-1", "pass"), JourneyRef("JNY-2", "fail")])
    assert requirement_verdict(r) == FAIL


def test_unverified_is_not_run_never_fail():
    r = _req("SPN-PRD-a", 0.0, [JourneyRef("JNY-1", "unverified")])
    assert requirement_verdict(r) == NOT_RUN


def test_partial_coverage_is_not_run():
    r = _req("SPN-PRD-a", 0.5, [JourneyRef("JNY-1", "pass")])
    assert requirement_verdict(r) == NOT_RUN


def test_no_journeys_is_not_run():
    assert requirement_verdict(_req("SPN-PRD-a", 0.0, [])) == NOT_RUN


def test_req_rows_have_variable_width(sample_trace_path, sample_manifest_path):
    reqs, _ = load_trace(sample_trace_path)
    m = Manifest.from_path(sample_manifest_path)
    rows = req_rows(reqs, m)
    by_id = {r[0]: r for r in rows}
    assert by_id["SPN-PRD-session-management"][3:] == ["JNY-AUTH-06"]
    assert by_id["SPN-GUI-calendar-day-view"][3:] == ["JNY-EPIS-10", "JNY-EPIS-07"]
    assert by_id["SPN-PRD-audit-log"][3:] == []


def test_uat_rows_invert_the_mapping(
    sample_trace_path, sample_graph_path, sample_manifest_path
):
    reqs, _ = load_trace(sample_trace_path)
    titles = load_journeys(sample_graph_path)
    m = Manifest.from_path(sample_manifest_path)
    rows = uat_rows(reqs, titles, m)
    by_case = {r[0]: r for r in rows}
    assert by_case["UAT-JNY-EPIS-10"][1] == "Opening a Day From the Calendar"
    assert by_case["UAT-JNY-EPIS-10"][3] == "JNY-EPIS-10"
    assert by_case["UAT-JNY-EPIS-10"][4:] == ["SPN-GUI-calendar-day-view"]


def test_uat_rows_carry_the_journey_verdict(
    sample_trace_path, sample_graph_path, sample_manifest_path
):
    reqs, _ = load_trace(sample_trace_path)
    titles = load_journeys(sample_graph_path)
    m = Manifest.from_path(sample_manifest_path)
    by_case = {r[0]: r for r in uat_rows(reqs, titles, m)}
    assert by_case["UAT-JNY-AUTH-06"][2] == PASS
    assert by_case["UAT-JNY-EPIS-07"][2] == FAIL
    assert by_case["UAT-JNY-EPIS-10"][2] == NOT_RUN


def test_journey_validating_nothing_in_scope_is_absent(
    sample_trace_path, sample_graph_path, sample_manifest_path
):
    reqs, _ = load_trace(sample_trace_path)
    titles = load_journeys(sample_graph_path)
    m = Manifest.from_path(sample_manifest_path)
    assert "UAT-JNY-ORPHAN-01" not in {r[0] for r in uat_rows(reqs, titles, m)}


def test_rows_are_ordered_by_id(sample_trace_path, sample_manifest_path):
    reqs, _ = load_trace(sample_trace_path)
    m = Manifest.from_path(sample_manifest_path)
    ids = [r[0] for r in req_rows(reqs, m)]
    assert ids == sorted(ids)
