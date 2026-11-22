# XWEB chart programme — consolidated ARM64 release set and guarded deployment procedure

**Status: preparation only.** Nothing in this document builds, stages or activates anything on a site, runs a production migration, or authorises one. Producing the CI artifacts below is allowed development-plane work; **every step marked OWNER needs the Product Owner's explicit, release-specific approval and is run by the owner**, never by an agent.

## 1. Release set

| Part                          | What it contains                                                                                                             | Built by                                                                                         |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Frontend — LAN dashboard      | Next production runtime for `http://172.18.48.66:8082` (API) / `ws://172.18.48.66:8082/api/v1/telemetry/live`, auth `local`  | `Frontend Release Artifact` workflow (`ubuntu-24.04-arm`)                                        |
| Frontend — protected HTTPS    | Same exact source, origin-bound to the external HTTPS origin (second artifact at the same SHA)                               | same workflow run, `external_origin` input                                                       |
| Backend — telemetry-service   | Image with the optional `view_settings` Saved Dashboard field and Alembic migration `20261122_0041` (additive nullable JSON) | `Offline Bundle` workflow, `platform=linux/arm64` (runtime images and schema from the exact SHA) |
| Device Agent / gateway / MQTT | **Unchanged.** The on-site Device Agent lineage (`nexolab/quick-agent:1490`) is not replaced by this release.                | —                                                                                                |

Both parts must be built from **one exact `main` SHA** that contains PR #1667 (backend) and the chart programme (#1644 … #1683). Pin it only after exact-head CI and the Merge Gate are green for that commit.

## 2. Compatibility and ordering

- The API change is **additive and optional**: older frontends never send `view_settings` (the server preserves a stored view when the field is omitted, and `null` clears it); a missing or corrupt stored value reads as "no saved view". The migration only adds a nullable column (metadata-only change in PostgreSQL).
- A **new frontend on an old API** is safe: saving a view fails with an explicit message («Сервер не підтримує збереження вигляду аналізу.») instead of pretending to save.
- Therefore the safe order is **backend first, frontend second**, and either part can be rolled back independently.
- **Rollback of the backend image does not require a schema downgrade**: an older service ignores the extra nullable column. The `20261122_0041` downgrade deliberately refuses to run while operator-authored views exist; use image rollback, not downgrade, unless the views were exported and cleared by an approved procedure.

## 3. Evidence already produced before the release decision

- Backend: the 17 view-settings tests and the whole Saved Dashboard suite (48 passed, 1 skipped) pass against an isolated PostgreSQL 16 whose schema is built by the real Alembic chain; 9/9 migration scenarios (upgrade from `20261118_0040` with a seeded legacy row, additive nullable column, legacy rows read as no view, downgrade refusal with saved views, downgrade after clearing, idempotent re-upgrade, single head).
- Browser acceptance against the real backend and PostgreSQL in CI (saved view round trip, custom period) — see the real-stack acceptance pull requests of the XWEB programme (linked from the release record).
- The container supply-chain gate for the backend images is governed by `docs/security/cve-2026-124709-assessment.md`; **do not build the release set from a commit whose gate was bypassed**.

## 4. Build the artifacts (development plane, no site contact)

Run from a clean checkout with `gh` authenticated. `FINAL_SHA` is the approved 40-character `main` SHA.

```bash
# Frontend: LAN + protected HTTPS artifacts at the same source
gh workflow run "Frontend Release Artifact" \
  -f source_ref="$FINAL_SHA" \
  -f api_base_url="http://172.18.48.66:8082" \
  -f websocket_url="ws://172.18.48.66:8082/api/v1/telemetry/live" \
  -f auth_provider="local" \
  -f organization_id="00000000-0000-0000-0000-000000000001" \
  -f external_origin="https://nexolab-edge-01.tail7f9b04.ts.net"

# Backend recovery/update bundle for the Raspberry Pi (linux/arm64): use the inputs of the last
# accepted bundle (dashboard origin, API/WebSocket URLs, auth provider local, external origin).
gh workflow run "Offline Bundle" -f platform=linux/arm64 -f runtime_source_ref="$FINAL_SHA" ...
```

The values above are the contract recorded by the last accepted frontend release (run `44954810847`); the owner must confirm them against the site before any dispatch. After the runs finish: download both artifacts, record the **ZIP SHA-256**, source SHA, build IDs, platform and Node baseline from the manifests, and attach the run URLs to the release issue.

## 5. Guarded deployment (OWNER-run, one explicit approval per step)

Reuse the repository's guarded, source-pinned pattern; do not improvise commands on the site.

1. **Authorise the exact release.** The owner names the source SHA, the artifact SHA-256 values, the migration `20261122_0041` and the affected routes. No automatic site action.
2. **Preflight (read-only).** Running LAN/HTTPS identities and build IDs (`/api/runtime-identity`), backend container IDs and images, Telemetry `/health/ready`, Device Agent `/health`, free disk (> 20 GiB), the previous frontend release and rollback manifest. Run `scripts/check-frontend-entrypoint-parity.py` read-only before and after.
3. **Backup and restore proof (blocker #1428 is still open).** Take the guarded PostgreSQL backup (`scripts/nexolab-safe-pg-incident-backup.sh`, `docs/operations/incident-postgresql-backup-1428.md`) and verify an isolated restore **off the production host** before any migration. The owner acknowledges that independent encrypted off-device DR is not complete.
4. **Backend update.** Install the new telemetry-service image through the documented offline-bundle update (`docs/operations/offline-installation.md` §6) with the same external environment files; it runs the single Alembic upgrade to `20261122_0041`. Do not restart or modify the Device Agent, MQTT, object storage, Docker/IPAM or any RS-485 bus. Verify `/health/ready`, that telemetry samples keep advancing and that an existing Saved Dashboard loads.
5. **Frontend update.** Consume the verified artifacts with `deploy-current-head-raspberry-pi.sh --frontend-artifact PATH` (or the #1522/#1638 guarded scripts regenerated with only the release constants changed). **Lesson from #1638:** the LAN image must be built from a **tar-streamed context** and compared **file by file** with the artifact (BuildKit context sync silently reused stale `.next` content when sizes and normalised mtimes were identical). Keep the previous image and HTTPS release for rollback; never re-run a failed `execute`.
6. **Verify after activation.** Identity API reports the pinned source/build on both entrypoints; five backend container IDs unchanged except telemetry-service; telemetry still advancing; authenticated browser on LAN and HTTPS: Saved Dashboard charts, statistics table, density control (also Energy and Refrigeration), state lanes, events table, the five range presets and the custom period on Overview and Energy, partial-history notice, saved analysis view (save, reload, restore; viewer cannot save), Save PNG / XLSX / print report, Live with up to 24 channels grouped by device, 390 px and desktop; no client/API errors; no acquisition requests added by chart interactions. **Measure density timings on the Pi and record them labelled as Pi measurements.**
7. **Rollback** with the release's rollback command (previous frontend image/HTTPS release; previous telemetry-service image without schema downgrade).
8. **Record evidence** in `.project/CURRENT_STATE.md`, `.project/LAST_CHECKPOINT.json` and the release issue; do not mark the site green or print the operator update-ready signal without that runtime proof.

## 6. Not covered / still open

Offline reboot or power-cycle (#1606), independent encrypted DR (#1428), Docker/LAN CIDR overlap (#1409/#1399), Pi density measurements, a signed-in owner browser review, real-controller relay/defrost/alarm semantics and the Embraco ×0.01 °C scale (#1603/#1625).

## 7. Boundaries

No Modbus or hardware write, no acquisition or polling change from the UI, no production database migration or site activation by an agent, no secret handling, no weakened security gate or broad vulnerability exception.
