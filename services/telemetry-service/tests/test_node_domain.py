from __future__ import annotations

import pytest

from app.nodes.domain import (
    ClockStatus,
    NodeTopicAuthorizationError,
    NodeTopicStream,
    authorize_node_topic,
    build_node_topic,
    classify_clock_offset,
    generate_provisioning_secret,
    hash_provisioning_secret,
    verify_provisioning_secret,
)


def test_topic_namespace_is_exact_and_owned() -> None:
    topic = build_node_topic("org-a", "edge-01", NodeTopicStream.TELEMETRY)
    assert topic == "nexolab/v1/org-a/edge-01/telemetry"
    assert (
        authorize_node_topic(
            organization_id="org-a",
            node_id="edge-01",
            topic=topic,
        )
        is NodeTopicStream.TELEMETRY
    )

    for rejected in (
        "nexolab/v1/org-a/edge-02/telemetry",
        "nexolab/v1/org-b/edge-01/telemetry",
        "nexolab/v1/org-a/edge-01/telemetry/raw",
        "nexolab/v1/org-a/edge-01/+",
        "nexolab/v1/org-a/edge-01/unknown",
    ):
        with pytest.raises(NodeTopicAuthorizationError):
            authorize_node_topic(
                organization_id="org-a",
                node_id="edge-01",
                topic=rejected,
            )


def test_clock_offset_policy_has_deterministic_boundaries() -> None:
    assert (
        classify_clock_offset(None, warning_ms=30_000, critical_ms=120_000)
        is ClockStatus.UNKNOWN
    )
    assert (
        classify_clock_offset(29_999, warning_ms=30_000, critical_ms=120_000)
        is ClockStatus.OK
    )
    assert (
        classify_clock_offset(-30_000, warning_ms=30_000, critical_ms=120_000)
        is ClockStatus.WARNING
    )
    assert (
        classify_clock_offset(119_999, warning_ms=30_000, critical_ms=120_000)
        is ClockStatus.WARNING
    )
    assert (
        classify_clock_offset(-120_000, warning_ms=30_000, critical_ms=120_000)
        is ClockStatus.CRITICAL
    )


def test_provisioning_secret_is_salted_and_verifiable() -> None:
    secret = generate_provisioning_secret()
    salt, digest, fingerprint = hash_provisioning_secret(secret)

    assert secret.startswith("nxl_node_")
    assert len(salt) == 64
    assert len(digest) == 64
    assert len(fingerprint) == 16
    assert secret not in {salt, digest, fingerprint}
    assert verify_provisioning_secret(
        secret,
        salt_hex=salt,
        expected_hash_hex=digest,
    )
    assert not verify_provisioning_secret(
        f"{secret}x",
        salt_hex=salt,
        expected_hash_hex=digest,
    )
