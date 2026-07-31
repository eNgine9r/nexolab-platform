# NEXOLAB offline-readiness baseline

**Baseline date:** 2026-07-31  
**Verified `main`:** `8371ee59e76e64963405706be79fc4a909f9fac9`  
**Profile:** `LOCAL_LAN`

This checklist classifies dependencies and separates static architecture review from executed offline acceptance.

## 1. Dependency classes

| Dependency or capability     | Classification                                   | Offline behavior                                                               |
| ---------------------------- | ------------------------------------------------ | ------------------------------------------------------------------------------ |
| Next.js dashboard            | Local mandatory                                  | Runs from a local process/container and uses local API/WebSocket origins       |
| FastAPI Telemetry Service    | Local mandatory                                  | Runs against local PostgreSQL, MQTT and optional local MinIO                   |
| PostgreSQL 16                | Local mandatory                                  | Central source of truth; named volume; no standard host port exposure          |
| Eclipse Mosquitto            | Local mandatory                                  | Local edge and central brokers; persistent data volumes                        |
| Edge SQLite                  | Local mandatory                                  | Stores outbound telemetry while central/MQTT delivery is unavailable           |
| MinIO                        | Local mandatory when image workflows are enabled | Local private S3-compatible storage; can be disabled at service level          |
| Serial/Modbus libraries      | Local mandatory on edge hardware                 | Read-only acquisition; no internet dependency                                  |
| Docker/Compose               | Local packaging/runtime dependency               | Must be preinstalled or included in the site installation procedure            |
| GitHub/GitHub Actions        | Development and delivery only                    | Not required after artifacts reach the local site                              |
| npm/PyPI                     | Development and connected build only             | Must not be contacted by the installed runtime                                 |
| GHCR/Docker Hub              | Connected installation only today                | Must be replaced by a local OCI bundle for guaranteed offline installation     |
| Supabase Auth                | Optional online                                  | No client is created when variables are absent                                 |
| External OIDC/JWKS           | Optional online                                  | Local public key configuration is supported; external JWKS cannot be mandatory |
| Tailscale                    | Optional remote access                           | Local LAN runtime continues without it                                         |
| External S3                  | Optional online                                  | Local MinIO is the standard fallback                                           |
| CDN fonts/assets             | Prohibited for core runtime                      | No mandatory instance was found in the inspected frontend                      |
| External telemetry/analytics | Prohibited for core runtime                      | No mandatory instance was found in the inspected configuration                 |
| Paid runtime API/service     | Prohibited                                       | Core operation must not depend on it                                           |

## 2. Readiness assessment

Status meanings:

- **Verified** — supported by inspected code/configuration and relevant execution evidence.
- **Static pass** — code/configuration supports the requirement, but this Work Package did not execute the runtime.
- **Partial** — some layers are implemented or evidenced, but the complete requirement is not accepted.
- **Missing** — required artifact or evidence was not found.

| Gate                                                               | Status                           | Evidence and boundary                                                                                  |
| ------------------------------------------------------------------ | -------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Core data path has no cloud dependency                             | Static pass                      | Edge, MQTT, FastAPI, PostgreSQL, MinIO and dashboard have local configurations                         |
| Browser assets work without remote fonts/CDN                       | Static pass                      | Root layout imports local CSS and system fonts; no mandatory CDN/font endpoint was found               |
| Edge acquisition survives central/MQTT outage                      | Verified for narrow scope        | 2026-07-23 combined Modbus soak recorded SQLite queue growth, reconnect and drain                      |
| Edge hardware remains read-only                                    | Static pass plus narrow evidence | Validated drivers use FC03; hardware override remains explicit; no write path was found                |
| Central services start without internet after images exist locally | Static pass                      | Compose topology is local and loopback-bound                                                           |
| Clean disconnected installation                                    | Missing                          | Default image acquisition uses GHCR/Docker Hub; no accepted local OCI bundle exists                    |
| Disconnected update package                                        | Missing                          | No versioned offline update bundle and manifest have been accepted                                     |
| Offline rollback preserving data                                   | Partial                          | Scripts/runbooks preserve named volumes; full disconnected update/rollback proof is missing            |
| Secure local operator authentication                               | Partial                          | JWT validation exists; Supabase is optional; production offline login/identity authority is unresolved |
| Local authorization/RBAC                                           | Partial                          | Backend/frontend contracts exist; complete disconnected operator acceptance is not established         |
| PostgreSQL backup procedure                                        | Static pass                      | Logical backup runbook exists                                                                          |
| PostgreSQL restore proof on current baseline                       | Missing in this audit            | Procedure exists, but no current verified artifact was inspected                                       |
| MinIO backup/restore proof                                         | Missing                          | Named storage exists; complete object backup/restore evidence was not found                            |
| MQTT persistence/recovery                                          | Partial                          | Edge MQTT outage is evidenced; full central broker/host recovery package is not                        |
| Host restart/reboot                                                | Partial                          | Focused restart tooling exists; complete current central/edge evidence is not consolidated             |
| Power-loss recovery                                                | Missing                          | No accepted controlled power-loss evidence was found                                                   |
| Logs/health/diagnostics remain local                               | Static pass                      | Local health, readiness, metrics and Compose logs are available                                        |
| Retention is bounded                                               | Static pass                      | Central retention policy and batch limits are configured                                               |
| Production/site cutover                                            | Not performed                    | Explicitly outside Issue #183                                                                          |

## 3. Runtime external-call budget

For an accepted disconnected runtime, the following must be zero after installation:

- npm/PyPI package downloads;
- Docker registry pulls;
- Supabase requests;
- external JWKS fetches;
- remote fonts or CDN assets;
- analytics/telemetry delivery;
- online license checks;
- mandatory cloud API calls.

Optional remote-access or cloud integrations must fail independently and show an explicit offline/disabled state.

## 4. Offline installation gap

The largest current gap is artifact delivery, not the local service topology.

A complete bundle must include:

- pinned OCI images for dashboard, Telemetry Service, Device Agent, Mosquitto, PostgreSQL, MinIO and MinIO Client;
- image digests and checksums;
- architecture manifest for `amd64` and required `arm64` targets;
- Compose files and validated environment templates;
- migration and seed tooling;
- local verification scripts;
- upgrade and rollback metadata;
- SBOM and license inventory;
- storage-size estimates;
- an operator procedure that never downloads from the internet.

Issue #187 is the owning Work Package.

## 5. Offline authentication gap

Current choices are:

- `AUTH_MODE=disabled`, which is local but not an accepted production security posture;
- JWT validation with a local public key, which is technically offline-capable but lacks a complete local login/identity lifecycle;
- optional Supabase Auth, which is online and cannot be mandatory;
- optional external JWKS, which is online and cannot be the only validation source.

Issue #188 must select and prove a fail-closed local operator authentication profile.

## 6. Recovery gap

Existing procedures are useful but do not form one current acceptance package. Required proof includes:

- PostgreSQL backup and isolated restore;
- MinIO object backup and restore;
- central MQTT persistence;
- edge SQLite outbox preservation;
- service and host restart;
- update rollback with named-volume identity preservation;
- stale/offline/live UI transitions;
- controlled power interruption where explicitly approved.

Issue #189 owns the consolidated recovery evidence.

## 7. Acceptance rules

Offline readiness is complete only when:

1. a clean supported host can install from local media with networking disabled;
2. the core stack starts and becomes ready without external DNS or HTTP;
3. a browser completes the main local workflows;
4. edge simulator mode and the approved hardware mode do not require internet;
5. authentication and authorization remain secure and usable locally;
6. backup, restore, update and rollback are executed and evidenced;
7. power loss or its explicitly approved equivalent is tested;
8. optional online services can be removed without data loss or core failure.
