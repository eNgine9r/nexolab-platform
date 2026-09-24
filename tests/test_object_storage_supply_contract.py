from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "infrastructure/object-storage/Dockerfile").read_text(encoding="utf-8")
COMPOSE = (ROOT / "infrastructure/compose/compose.central.yaml").read_text(encoding="utf-8")
OFFLINE = (ROOT / "infrastructure/offline/compose.central.offline.yaml").read_text(encoding="utf-8")
HELPER = (ROOT / "scripts/object-storage-s3.py").read_text(encoding="utf-8")
TELEMETRY_WORKFLOW = (ROOT / ".github/workflows/telemetry-service.yml").read_text(encoding="utf-8")
OFFLINE_AUTH_ACCEPTANCE = (ROOT / "scripts/run-offline-auth-acceptance.sh").read_text(encoding="utf-8")


def test_versitygw_release_is_exact_and_checksum_pinned_for_both_architectures() -> None:
    assert "VERSITYGW_VERSION=1.8.0" in DOCKERFILE
    assert "2ba2c734d10d2c4e651d03182cb4b246656bc735a2f282db7b0b73fba6073467" in DOCKERFILE
    assert "b34051d33f5a9c457f790896acb7bd7d7e15ad8d92efb70616b924f37e401910" in DOCKERFILE
    assert "sha256sum -c -" in DOCKERFILE
    assert "FROM scratch" in DOCKERFILE


def test_central_runtime_uses_local_versitygw_build_not_external_minio_images() -> None:
    assert "../object-storage" in COMPOSE
    assert "nexolab/object-storage:versitygw-v1.8.0" in COMPOSE
    assert "quay.io/minio/" not in COMPOSE
    assert "minio/minio:" not in COMPOSE
    assert "minio/mc:" not in COMPOSE
    assert "ROOT_ACCESS_KEY_ID" in COMPOSE
    assert 'VGW_HEALTH: "/health"' in COMPOSE


def test_bootstrap_uses_repository_s3_helper_not_mc() -> None:
    assert "object-storage-s3.py" in COMPOSE
    assert "mc alias" not in COMPOSE
    assert "mc mb" not in COMPOSE
    assert "mc anonymous" not in COMPOSE
    assert "boto3" in HELPER
    assert "assert-private" in HELPER
    assert "mirror-upload" in HELPER
    assert "mirror-download" in HELPER


def test_offline_runtime_reuses_telemetry_image_for_s3_bootstrap() -> None:
    assert "OFFLINE_OBJECT_STORAGE_IMAGE" in OFFLINE
    assert "OFFLINE_TELEMETRY_IMAGE" in OFFLINE
    assert "OFFLINE_MINIO_CLIENT_IMAGE" not in OFFLINE


def test_telemetry_ci_provides_ephemeral_posix_root_to_versitygw() -> None:
    assert "--tmpfs /data:rw,nosuid,nodev,noexec" in TELEMETRY_WORKFLOW
    assert "posix /data" in TELEMETRY_WORKFLOW


def test_offline_auth_acceptance_builds_local_object_storage_before_no_build_start() -> None:
    assert "compose build minio telemetry-service telemetry-migrate" in OFFLINE_AUTH_ACCEPTANCE
    assert "compose up --detach --no-build" in OFFLINE_AUTH_ACCEPTANCE
