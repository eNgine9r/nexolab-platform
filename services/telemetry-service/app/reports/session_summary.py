from __future__ import annotations


def frozen_session_summary(
    snapshot: object, *, organization_id: str, session_id: str
) -> dict[str, str] | None:
    """Read display identity only from the report's existing immutable source."""
    if not isinstance(snapshot, dict):
        return None
    if (
        snapshot.get("schema") != "nexolab.report-source.v1"
        or snapshot.get("organization_id") != organization_id
        or snapshot.get("session_id") != session_id
    ):
        return None
    metadata = snapshot.get("metadata")
    source = metadata.get("session") if isinstance(metadata, dict) else None
    if not isinstance(source, dict) or (
        source.get("id") != session_id
        or source.get("organization_id") != organization_id
    ):
        return None
    summary: dict[str, str] = {}
    for key, limit in (("session_number", 64), ("title", 256), ("test_object", 256)):
        value = source.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            return None
        summary[key] = value
    return summary
