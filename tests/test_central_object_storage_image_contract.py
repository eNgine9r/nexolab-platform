from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (ROOT / "infrastructure/compose/compose.central.yaml").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / "infrastructure/compose/.env.central.example").read_text(encoding="utf-8")
IMAGE = "nexolab/object-storage:versitygw-v1.8.0"


def test_central_compose_defaults_to_repository_owned_versitygw_image() -> None:
    assert f"${{OBJECT_STORAGE_IMAGE:-{IMAGE}}}" in COMPOSE
    assert "context: ../object-storage" in COMPOSE
    assert "quay.io/minio/" not in COMPOSE
    assert "minio/minio:" not in COMPOSE
    assert "minio/mc:" not in COMPOSE


def test_central_env_example_matches_local_object_storage_default() -> None:
    assert f"OBJECT_STORAGE_IMAGE={IMAGE}" in ENV_EXAMPLE
    assert "MINIO_IMAGE=" not in ENV_EXAMPLE
    assert "MINIO_CLIENT_IMAGE=" not in ENV_EXAMPLE
