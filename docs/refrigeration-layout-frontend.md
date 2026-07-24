# Refrigeration layout frontend integration

The refrigeration equipment screen uses the same explicit NEXOLAB runtime boundary as live telemetry.

## Runtime selection

```dotenv
NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
NEXT_PUBLIC_NEXOLAB_API_BASE_URL=http://<trusted-central-host>:8082
NEXT_PUBLIC_NEXOLAB_OPERATOR_ID=dashboard-operator
```

- `live` creates the typed HTTP refrigeration-layout repository.
- `demo` keeps the deterministic in-memory adapter and never contacts the central backend.
- No PostgreSQL, MinIO or service credentials are exposed to the browser.
- `NEXT_PUBLIC_NEXOLAB_OPERATOR_ID` is an audit actor label, not an authentication secret.

## Operator workflow

1. The workspace loads the current draft, current published revision and immutable history.
2. The editor reads the backend ETag and saves normalized placements with `If-Match`.
3. A selected JPEG, PNG or WebP file is previewed locally while multipart upload is in progress.
4. After object-storage upload succeeds, the returned image ID is attached through a new draft version.
5. Publishing creates an immutable revision and refreshes current publication and history.
6. Restoring a revision creates another draft version; the historical record is never mutated.

## Conflict recovery

Save, photo attachment, publish and restore use the loaded draft version. HTTP `409 layout_version_conflict` is mapped to the typed frontend conflict with expected and actual versions.

The UI does not overwrite local marker positions or the current upload preview. The operator may:

- continue editing locally;
- reload the current server draft after explicit confirmation;
- retry attachment for an image that already reached object storage.

Reloading the server draft is the only conflict action that intentionally discards local unsaved marker changes.

## Image rules

The browser performs an early format and 15 MB check. The backend remains authoritative and validates the actual image bytes, dimensions and declared MIME type before persisting object metadata.

Signed object-storage URLs are treated as temporary display URLs. Layout persistence stores only the immutable image ID returned by the backend.

## Validation coverage

Frontend tests cover runtime mode selection, ETag and `If-Match` transport semantics, multipart upload, publication history, restoration and stale-writer recovery while preserving local marker state.
