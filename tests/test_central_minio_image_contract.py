from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (ROOT / "infrastructure/compose/compose.central.yaml").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / "infrastructure/compose/.env.central.example").read_text(encoding="utf-8")
SERVER = "quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z"
CLIENT = "quay.io/minio/mc:RELEASE.2025-08-13T08-35-41Z"


def test_central_compose_defaults_to_pinned_quay_minio_images() -> None:
    assert f"${{MINIO_IMAGE:-{SERVER}}}" in COMPOSE
    assert f"${{MINIO_CLIENT_IMAGE:-{CLIENT}}}" in COMPOSE
    assert "MINIO_IMAGE:-minio/minio:" not in COMPOSE
    assert "MINIO_CLIENT_IMAGE:-minio/mc:" not in COMPOSE


def test_central_env_example_matches_pinned_quay_defaults() -> None:
    assert f"MINIO_IMAGE={SERVER}" in ENV_EXAMPLE
    assert f"MINIO_CLIENT_IMAGE={CLIENT}" in ENV_EXAMPLE
    assert "MINIO_IMAGE=minio/minio:" not in ENV_EXAMPLE
    assert "MINIO_CLIENT_IMAGE=minio/mc:" not in ENV_EXAMPLE
