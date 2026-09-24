# Refrigeration layout backend

The production refrigeration-layout backend is owned by Telemetry Service and uses PostgreSQL for versioned metadata plus a private S3-compatible bucket for equipment photos.

## Persistence model

- `equipment_images` stores immutable object metadata, SHA-256, dimensions and the private storage key.
- `refrigeration_layout_drafts` stores one mutable, equipment-scoped draft with a monotonically increasing version.
- `refrigeration_layout_revisions` stores append-only published revisions. PostgreSQL rejects `UPDATE` and `DELETE` on this table.
- Placements remain normalized to the inclusive range `0..1` and sensor identifiers must be unique within a layout.
- Alembic revision `20260724_0007` follows the existing audit-hardening revision `20260724_0006`.

## REST contract

```text
GET  /api/v1/equipment/{equipment_id}/layout/draft
PUT  /api/v1/equipment/{equipment_id}/layout/draft
POST /api/v1/equipment/{equipment_id}/layout/publish
GET  /api/v1/equipment/{equipment_id}/layout/published
GET  /api/v1/equipment/{equipment_id}/layout/history
POST /api/v1/equipment/{equipment_id}/layout/history/{revision_id}/restore
POST /api/v1/equipment/{equipment_id}/images
```

Draft reads return an ETag such as `W/"layout-draft-v3"`. Draft save, publish and restore require the same value in `If-Match`. A stale writer receives HTTP `409` with `layout_version_conflict`, `expected_version` and `actual_version`; the persisted draft is not overwritten.

Equipment-photo upload is multipart and requires `X-Actor-Id`. The service reads at most the configured size limit, validates JPEG/PNG/WebP from the bytes with Pillow, verifies the declared media type, extracts dimensions and stores the object privately. API responses contain short-lived signed URLs rather than object-storage credentials or public bucket access.

## Central deployment

`compose.central.yaml` provides private S3-compatible storage through VersityGW v1.8.0 and one dedicated persistent named volume:

```text
nexolab-central-object-storage-versitygw-data
```

The logical Compose service key remains `minio` temporarily for installed LOCAL_LAN endpoint and rollback compatibility, but it runs VersityGW rather than MinIO. The API therefore continues to use `http://minio:9000` internally. `OBJECT_STORAGE_PUBLIC_ENDPOINT_URL` must be a trusted URL reachable by the operator browser because that hostname is embedded into signed image URLs. The default example binds the object-storage API to loopback only.

Existing site credentials remain accepted through compatibility aliases:

```dotenv
MINIO_ROOT_USER=nexolab-storage
MINIO_ROOT_PASSWORD=<long-random-secret>
```

Do not expose the object-storage API to an untrusted network. The repository-owned S3 bootstrap helper creates the configured bucket and verifies that anonymous access remains disabled. The legacy `nexolab-central-object-storage-data` MinIO volume is not mounted into VersityGW; migration/cutover requires a separately approved S3-level export/import procedure.

## Failure semantics

- If object upload fails, no image metadata is committed.
- If database insertion fails after object upload, the service attempts to delete the uploaded object before propagating the error.
- Published revisions reference immutable image metadata and cannot be changed in place.
- Restoring history copies a revision into a new draft version; it never mutates the historical row.
- PostgreSQL and object-storage backups must be treated as one recovery set.
