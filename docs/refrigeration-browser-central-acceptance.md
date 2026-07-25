# Refrigeration browser-to-central acceptance gate

This gate runs the production NEXOLAB frontend against the real central stack:

- Next.js production server;
- FastAPI telemetry service;
- PostgreSQL 16;
- private S3-compatible MinIO storage;
- Mosquitto required by the central service lifecycle;
- Chromium through Playwright.

It does not use the in-memory refrigeration repository, mocked HTTP transport, fake signed URLs or component-only rendering.

## Acceptance sequence

1. Start an isolated central stack with dedicated ports, Docker network and named volumes.
2. Open `showcase-106-01` in live mode and verify draft `v1` comes from PostgreSQL.
3. Upload a valid PNG through the browser.
4. Verify the returned image URL contains AWS-style signing parameters and returns HTTP `200` from MinIO.
5. Enter layout edit mode, reset the empty production draft to the 48-sensor equipment template and save draft `v3`.
6. Publish immutable revision `r1`; publication advances the mutable draft to `v4`.
7. Open a second isolated browser context at `v4`.
8. Move the same marker differently in both contexts.
9. Save operator A as `v5`.
10. Save stale operator B and require a `v4` versus `v5` conflict without losing B's local marker coordinate.
11. Explicitly reload server `v5` in operator B and verify the winning coordinate replaces the local stale value.
12. Query the final REST, PostgreSQL and MinIO state and retain evidence.

## Local execution

Requirements:

- Docker with Compose v2;
- Node.js 22 or newer;
- npm 10 or newer;
- Chromium dependencies supported by Playwright.

Run:

```bash
bash scripts/run-refrigeration-browser-acceptance.sh
```

The runner generates non-production PostgreSQL and MinIO credentials, uses these default loopback ports, and removes the complete stack afterward:

```text
Frontend      127.0.0.1:13000
Central API   127.0.0.1:18082
MQTT          127.0.0.1:11884
MinIO API     127.0.0.1:19000
MinIO console 127.0.0.1:19001
```

Override ports with `ACCEPTANCE_WEB_PORT`, `ACCEPTANCE_API_PORT`, `ACCEPTANCE_MQTT_PORT`, `ACCEPTANCE_OBJECT_STORAGE_PORT` and `ACCEPTANCE_OBJECT_STORAGE_CONSOLE_PORT`.

Set `KEEP_ACCEPTANCE_STACK=1` only for interactive diagnostics. The operator must later run the same two Compose files with `down --volumes` and the generated `COMPOSE_PROJECT_NAME`.

## Evidence

The default evidence directory is:

```text
runtime/evidence/refrigeration-browser-acceptance-<UTC timestamp>
```

GitHub Actions writes to `acceptance-evidence/` and uploads the directory as a workflow artifact. Evidence contains:

- browser acceptance summary JSON;
- redacted signed-image metadata and HTTP result;
- conflict screenshot before recovery;
- screenshot after explicit server reload;
- Playwright HTML report, traces, screenshots and video on failure;
- PostgreSQL draft, revision and image rows;
- MinIO anonymous-access status and recursive object listing;
- Docker Compose state and complete central-stack logs.

Signed URL query values are not persisted in the summary. Only query parameter names, object path, origin and response metadata are retained.

## Isolation and safety

The acceptance override changes all long-lived services to `restart: "no"` and requires dedicated network and volume names. The local runner derives these names from a unique Compose project name. It never reuses the production `nexolab-central-*` volumes.

All browser-accessible endpoints bind to loopback. The MinIO bucket remains private; `mc anonymous get` evidence must report disabled anonymous access. The browser receives only a short-lived signed object URL.

## Pass criteria

The gate passes only when:

- the real browser flow completes without mocks;
- the signed MinIO object is readable but the bucket is not anonymous;
- PostgreSQL stores one mutable draft at `v5` with 48 placements;
- PostgreSQL stores immutable revision `r1` sourced from draft `v3` with 48 placements;
- the stale browser displays expected version `v4` and actual version `v5`;
- the stale browser retains its local coordinate until explicit reload;
- explicit reload resolves to the winning server coordinate;
- the production Next.js build succeeds.
