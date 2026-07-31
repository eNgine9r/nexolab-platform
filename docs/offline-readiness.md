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
| Edge SQLite                  | Local mandatory                                  | Stores outbound telemetry until the configured MQTT broker acknowledges QoS 1  |
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

| Gate                                                               | Status                           | Evidence and boundary                                                                                                                         |
| ------------------------------------------------------------------ | -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Core data path has no cloud dependency                             | Static pass                      | Edge, MQTT, FastAPI, PostgreSQL, MinIO and dashboard have local configurations                                                                |
| Browser assets work without remote fonts/CDN                       | Static pass                      | Root layout imports local CSS and system fonts; no mandatory CDN/font endpoint was found                                                      |
| Edge acquisition survives central/MQTT outage                      | Verified for narrow scope        | 2026-07-23 combined Modbus soak recorded SQLite queue growth, reconnect and drain to the MQTT boundary                                        |
| End-to-end MQTT-to-PostgreSQL durability                           | Missing — Issue #198             | Edge rows are deleted after broker QoS 1 acknowledgement while central persistence is still in memory; service termination can lose telemetry |
| Edge hardware remains read-only                                    | Static pass plus narrow evidence | Validated drivers use FC03; hardware override remains explicit; no write path was found                                                       |
| Central services start without internet after images exist locally | Static pass                      | Compose topology is local and loopback-bound                                                                                                  |
| Clean disconnected installation                                    | Missing                          | Default image acquisition uses GHCR/Docker Hub; no accepted local OCI bundle exists                                                           |
| Disconnected update package                                        | Missing                          | No versioned offline update bundle and manifest have been accepted                                                                            |
| Offline rollback preserving data                                   | Partial                          | Scripts/runbooks preserve named volumes; full disconnected update/rollback proof is missing                                                   |
| Secure local operator authentication                               | Partial                          | JWT validation exists; Supabase is optional; production offline login/identity authority is unresolved                                        |
| Local authorization/RBAC                                           | Partial                          | Backend/frontend contracts exist; complete disconnected operator acceptance is not established                                                |
| PostgreSQL backup procedure                                        | Static pass                      | Logical backup runbook exists                                                                                                                 |
| Central PostgreSQL fresh-volume restore software proof             | Verified software gate           | Merged PR #144 restores a custom dump into a fresh volume and verifies Alembic head, protected counts and hashes                              |
| MinIO fresh-volume backup/restore software proof                   | Verified software gate           | PR #144 restores the private bucket and verifies object count, bytes, metadata, SHA-256 and private access                                    |
| MQTT persistence/recovery                                          | Partial                          | PR #144 verifies Mosquitto persistence/Dynamic Security restore; #198 ingestion durability and actual-host recovery remain open               |
| Host restart/reboot                                                | Partial                          | Focused restart tooling exists; complete current central/edge evidence is not consolidated                                                    |
| Power-loss recovery                                                | Missing                          | No accepted controlled power-loss evidence was found                                                                                          |
| Logs/health/diagnostics remain local                               | Static pass                      | Local health, readiness, metrics and Compose logs are available                                                                               |
| Retention is bounded                                               | Static pass                      | Central retention policy and batch limits are configured                                                                                      |
| Production/site cutover                                            | Not performed                    | Explicitly outside Issue #183                                                                                                                 |

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

The largest installation gap is artifact delivery, not the local service topology.

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

## 6. Durability and recovery gap

The current MQTT-to-PostgreSQL handoff is not end-to-end durable. The Device Agent deletes edge SQLite records after broker QoS 1 acknowledgement, but the Telemetry Service persists through a bounded in-memory queue. A service termination during PostgreSQL outage can therefore discard an acknowledged event.

Issue #198 must implement a local durable central staging/replay boundary before restart and outage acceptance can claim no silent telemetry loss.

Merged PR #144 provides a repeatable encrypted software recovery gate for PostgreSQL, private MinIO objects and Mosquitto persistence/Dynamic Security. The drill restores into fresh volumes and verifies protected database state, MinIO object bytes/metadata/private access, broker policy, REST, WebSocket, MQTT TLS and Chromium flows. It explicitly does not prove the actual central host, scheduler, off-host storage, physical disks or production RPO/RTO.

Remaining proof includes:

- durable central ingestion staging and replay from Issue #198;
- execution and scheduling on the controlled central host;
- encrypted off-host copy and key custody;
- edge SQLite outbox preservation across host/power events;
- service and host restart on the real deployment;
- update rollback with named-volume identity preservation;
- stale/offline/live UI transitions;
- physical disk loss and controlled power interruption where explicitly approved.

Issue #189 owns this consolidated operational and hardware evidence after #198 closes the durability gap.

## 7. Acceptance rules

Offline readiness is complete only when:

1. a clean supported host can install from local media with networking disabled;
2. the core stack starts and becomes ready without external DNS or HTTP;
3. a browser completes the main local workflows;
4. edge simulator mode and the approved hardware mode do not require internet;
5. authentication and authorization remain secure and usable locally;
6. MQTT-to-PostgreSQL delivery remains recoverable across PostgreSQL outage and Telemetry Service restart;
7. backup, restore, update and rollback are executed and evidenced;
8. power loss or its explicitly approved equivalent is tested;
9. optional online services can be removed without data loss or core failure.
