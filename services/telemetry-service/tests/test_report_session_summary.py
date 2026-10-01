from copy import deepcopy

from app.reports.session_summary import frozen_session_summary


def snapshot():
    return {"schema": "nexolab.report-source.v1", "organization_id": "org-a", "session_id": "session-a", "metadata": {"session": {"id": "session-a", "organization_id": "org-a", "session_number": "NX-01", "title": "Випробування", "test_object": "Камера"}}}


def summary(value):
    return frozen_session_summary(value, organization_id="org-a", session_id="session-a")


def test_frozen_summary_does_not_modify_snapshot():
    value = snapshot()
    original = deepcopy(value)
    assert summary(value) == {"session_number": "NX-01", "title": "Випробування", "test_object": "Камера"}
    assert value == original


def test_legacy_and_malformed_metadata_have_no_invented_identity():
    for value in (None, [], {}, {"metadata": []}, {**snapshot(), "metadata": {"session": None}}):
        assert summary(value) is None
    for key, limit in (("session_number", 64), ("title", 256), ("test_object", 256)):
        for invalid in (None, 123, [], "", "  ", "x" * (limit + 1)):
            value = snapshot()
            value["metadata"]["session"][key] = invalid
            assert summary(value) is None


def test_report_identity_must_match_top_level_and_nested_source():
    for key in ("organization_id", "session_id", "schema"):
        value = snapshot()
        value[key] = "foreign"
        assert summary(value) is None
    for key in ("organization_id", "id"):
        value = snapshot()
        value["metadata"]["session"][key] = "foreign"
        assert summary(value) is None
