from __future__ import annotations

import json

from oq_compile.load import load_journeys, load_trace


def test_loads_requirements(sample_trace_path):
    reqs, _ = load_trace(sample_trace_path)
    assert len(reqs) == 3
    assert reqs[0].id == "SPN-PRD-session-management"
    assert reqs[0].level == "PRD"
    assert reqs[0].status == "Active"
    assert reqs[0].uat_verified_ratio == 1.0


def test_deduplicates_repeated_journeys(sample_trace_path):
    reqs, _ = load_trace(sample_trace_path)
    calendar = next(r for r in reqs if r.id == "SPN-GUI-calendar-day-view")
    assert [j.id for j in calendar.journeys] == ["JNY-EPIS-10", "JNY-EPIS-07"]


def test_preserves_verdicts(sample_trace_path):
    reqs, _ = load_trace(sample_trace_path)
    calendar = next(r for r in reqs if r.id == "SPN-GUI-calendar-day-view")
    assert calendar.journeys[0].verdict == "unverified"
    assert calendar.journeys[1].verdict == "fail"


def test_requirement_with_no_journeys(sample_trace_path):
    reqs, _ = load_trace(sample_trace_path)
    audit = next(r for r in reqs if r.id == "SPN-PRD-audit-log")
    assert audit.journeys == ()


def test_bare_list_has_no_scope_header(sample_trace_path):
    _, scope = load_trace(sample_trace_path)
    assert scope == ()


def test_accepts_dict_form_with_scope_header(sample_trace_scoped_path):
    # sample-trace-scoped.json is real `elspais trace --scope readiness
    # --values ... --format json` output, captured against the readiness
    # fixture -- not a hand-written approximation of the shape. A prior
    # version of this test invented a `requirements` rows key that does not
    # exist in real output (the real key is `nodes`), which is how a loader
    # bug that silently emptied every scoped report passed review.
    reqs, scope = load_trace(sample_trace_scoped_path)
    assert len(reqs) == 1
    assert reqs[0].id == "SPN-PRD-fixture-obligation"
    assert [j.id for j in reqs[0].journeys] == ["JNY-FIX-01"]
    assert scope == (
        "Scope: level PRD or GUI",
        "Scope selected 1 of 1 requirements",
    )


def test_dict_form_with_unrecognised_rows_key_fails_loud(tmp_path):
    p = tmp_path / "trace.json"
    p.write_text(json.dumps({"scope": [], "requirements": []}))
    try:
        load_trace(p)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "nodes" in str(e)
        assert "requirements" in str(e)
        assert "scope" in str(e)


def test_loads_journey_titles(sample_graph_path):
    titles = load_journeys(sample_graph_path)
    assert len(titles) == 4
    assert titles["JNY-AUTH-06"] == "Extending an Idle Session"
    assert titles["JNY-EPIS-10"] == "Opening a Day From the Calendar"
    assert titles["JNY-EPIS-07"] == "Duration Reasonableness Check on Save"
    assert titles["JNY-ORPHAN-01"] == "Validates Nothing In Scope"
    assert "SPN-PRD-session-management" not in titles


def test_missing_requirement_id_fails_loud(tmp_path):
    p = tmp_path / "trace.json"
    p.write_text(
        json.dumps(
            [
                {
                    "title": "A",
                    "level": "PRD",
                    "status": "Draft",
                    "uat_verified": {"ratio": 0.0},
                    "verified": {"ratio": 0.0, "carried": False},
                    "tested": {"failed": 0.0},
                    "journeys": [],
                }
            ]
        )
    )
    try:
        load_trace(p)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "requirement row 0" in str(e)
        assert "id" in str(e)


def test_missing_uat_verified_fails_loud(tmp_path):
    p = tmp_path / "trace.json"
    p.write_text(
        json.dumps(
            [
                {
                    "id": "SPN-PRD-a",
                    "title": "A",
                    "level": "PRD",
                    "status": "Draft",
                    "verified": {"ratio": 0.0, "carried": False},
                    "tested": {"failed": 0.0},
                    "journeys": [],
                }
            ]
        )
    )
    try:
        load_trace(p)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "requirement row 0" in str(e)
        assert "uat_verified" in str(e)


def test_missing_uat_verified_ratio_fails_loud(tmp_path):
    p = tmp_path / "trace.json"
    p.write_text(
        json.dumps(
            [
                {
                    "id": "SPN-PRD-a",
                    "title": "A",
                    "level": "PRD",
                    "status": "Draft",
                    "uat_verified": {},
                    "verified": {"ratio": 0.0, "carried": False},
                    "tested": {"failed": 0.0},
                    "journeys": [],
                }
            ]
        )
    )
    try:
        load_trace(p)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "requirement row 0" in str(e)
        assert "ratio" in str(e)


def test_missing_journey_id_fails_loud(tmp_path):
    p = tmp_path / "trace.json"
    p.write_text(
        json.dumps(
            [
                {
                    "id": "SPN-PRD-a",
                    "title": "A",
                    "level": "PRD",
                    "status": "Draft",
                    "uat_verified": {"ratio": 0.0},
                    "verified": {"ratio": 0.0, "carried": False},
                    "tested": {"failed": 0.0},
                    "journeys": [{"verdict": "pass"}],
                }
            ]
        )
    )
    try:
        load_trace(p)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "journey entry 0" in str(e)
        assert "id" in str(e)


def test_missing_journeys_key_fails_loud(tmp_path):
    """`journeys` was the last required field read with a `.get(... ) or []`
    default. An upstream rename would have yielded a full REQ sheet with every
    journey column blank and an entirely empty UAT sheet, at exit 0."""
    import pytest

    path = tmp_path / "trace.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "SPN-PRD-session-management",
                    "title": "Session Management",
                    "level": "PRD",
                    "status": "Active",
                    "uat_verified": {"ratio": 1.0},
                    "verified": {"ratio": 0.0, "carried": False},
                    "tested": {"failed": 0.0},
                    "validating_journeys": [{"id": "JNY-AUTH-06"}],
                }
            ]
        )
    )
    with pytest.raises(ValueError) as excinfo:
        load_trace(path)
    assert "journeys" in str(excinfo.value)


def test_empty_journeys_list_is_accepted(tmp_path):
    """A requirement with no validating journey is ordinary data; only an
    absent key is a defect."""
    path = tmp_path / "trace.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "SPN-PRD-audit-log",
                    "title": "Audit Log",
                    "level": "PRD",
                    "status": "Active",
                    "uat_verified": {"ratio": 0.0},
                    "verified": {"ratio": 0.0, "carried": False},
                    "tested": {"failed": 0.0},
                    "journeys": [],
                }
            ]
        )
    )
    reqs, _ = load_trace(path)
    assert reqs[0].journeys == ()


def test_graph_with_no_journey_nodes_fails_loud_when_journeys_are_cited(tmp_path):
    """A changed export shape or a renamed node-kind string narrows to nothing
    and every UAT row renders with a blank Description."""
    import pytest

    path = tmp_path / "graph.json"
    path.write_text(
        json.dumps(
            {
                "nodes": {
                    "JNY-AUTH-06": {
                        "id": "JNY-AUTH-06",
                        "kind": "UserJourney",
                        "label": "Extending an Idle Session",
                    }
                }
            }
        )
    )
    with pytest.raises(ValueError) as excinfo:
        load_journeys(path, cited_journeys=1)
    message = str(excinfo.value)
    assert "USER_JOURNEY" in message
    assert "UserJourney" in message


def test_graph_with_no_journey_nodes_is_fine_when_none_are_cited(tmp_path):
    path = tmp_path / "graph.json"
    path.write_text(json.dumps({"nodes": {}}))
    assert load_journeys(path, cited_journeys=0) == {}
