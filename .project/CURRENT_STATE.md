# NEXOLAB Current State

Updated: 2026-08-22

## State Model v2 boundary

NEXOLAB continuity uses durable repository state plus current GitHub observations. GitHub remains authoritative for current `main` HEAD, Issue/PR lifecycle, merge SHA and repository settings; those volatile facts do not require a dedicated reconciliation PR.

## Durable baselines

Accepted product source: `a2fd9496959764691860106c2f0625587fc707a2`.

Deployed product source: `6e387485b68fb862d9f82ae7f6000b1f5b672764`.

The accepted product baseline includes Issue #618 / PR #652. The deployed Raspberry Pi baseline is intentionally older and must not be represented as containing #618 or #607 until an actual controlled deployment occurs.

## Completed process hardening — Issues #646 / #648 / #650

Impact-aware CI, deterministic `npm ci`, exact-head external workflow aggregation, the state-only fast lane and State Model v2 are repository-side verified.

Issue #646 remains soft-blocked only on the repository setting that would technically protect `main`; the retained GitHub observation still reports branch protection disabled.

State Model v2 removes mandatory post-merge reconciliation PRs. Product Work Packages may ingest the previous accepted Work Package evidence when the next material state change occurs.

## Completed product Work Package — Issue #618

Issue #618 — **Restore Saved Dashboard CSV export browser acceptance on LOCAL_LAN** — completed through PR #652.

Accepted evidence:

- final verified PR head `3982e901f6732713fa23ea1650299eb6738a9f79`;
- Core CI run `32572681394`: PASS;
- Authenticated Dashboard Acceptance run `32572681396`: PASS;
- Offline Bundle run `32572681390`: PASS;
- `NEXOLAB Merge Gate`: PASS;
- production Chromium observed a real CSV download and the acceptance artifact contained the exported CSV;
- browser evidence retained `publicRequests: []` and `acquisitionMutations: []`;
- GitHub recorded squash merge `a2fd9496959764691860106c2f0625587fc707a2` on 2026-08-22.

Raspberry Pi repetition of the CSV acceptance remains unverified because `nexolab-edge-01` is offline in the Remote Desktop connector. This does not invalidate the accepted GitHub-hosted production-browser evidence.

## Active Work Package — Issue #607

Issue #607 — **Add dual RS-485 bus isolation for KK1 and KK2** — is active in branch `feat/607-dual-rs485-bus-isolation`.

Repository-backed architecture result:

- `AdaptiveAcquisitionScheduler` already owns jobs, workers, cooldown and scheduler metrics by `bus_id` and does not require a scheduler rewrite;
- the real single-bus restriction is the runtime composition layer: one serial setting/client/readers and one global operation lock;
- XJP60D catalog evidence maps KK2 to Unit IDs `101..115` and KK1 to `126..138`;
- repository evidence does not establish KK1/KK2 ownership for LE-01MP Unit IDs `200..203`, so the runtime must not guess it.

Current software candidate:

- adds explicit validated `RS485_BUS_CONFIG_JSON` bus bindings with stable `/dev/serial/by-id/...` identities;
- preserves legacy `SERIAL_DEVICE` / `rs485-main` behavior when explicit topology is absent;
- creates one `ModbusRTUClient`, reader set and physical operation lock per configured bus;
- preserves scheduler serialization within one bus while allowing separate bus workers to execute concurrently;
- uses an all-bus mutation guard for registry/topology mutations so configuration changes cannot race physical reads;
- partitions explicit XJP60D discovery by bus and persists newly responsive controllers as `discovery_only` on the bus where they were read;
- exposes bounded per-bus physical request rate, retry/timeout/error counters and latency average/p95/max;
- fails health closed when a configured bus with active targets has no stable device path;
- keeps configured-but-unused future buses `hardware_unverified` without pretending they are accepted;
- introduces no Modbus write function, cloud dependency or hardware cutover.

Architecture and operator contract: `docs/architecture/dual-rs485-bus-isolation.md` and `infrastructure/compose/.env.dual-rs485.example`.

## Runtime and hardware boundary

Issue #607 is currently **software candidate / hardware unverified**.

`nexolab-edge-01` remains offline in the Remote Desktop connector. No physical second adapter installation, field wiring move, site cutover, controller configuration write or Modbus write has been performed.

Future hardware acceptance requires the exact two stable `/dev/serial/by-id/...` adapter identities, simultaneous read-only polling evidence, one-bus disconnect isolation and reboot-stable bus mapping.

## Current blocker boundary

- #607: no software hard blocker; real hardware acceptance is unavailable while the Raspberry Pi connector is offline and physical cutover is not authorized.
- #646: branch-protection repository setting remains a soft access blocker.
- Security maintenance: four temporary `CVE-2026-14456` exceptions from Issue #598 are due for review/removal by **2026-08-26**, or earlier if a fixed Debian package becomes available or reachability assumptions change.

Known dependencies:

- #589 remains blocked on completion of #607 bus-aware architecture;
- #590 remains blocked on #589;
- #585 remains blocked pending explicit physical W2 / Unit 201 handback approval;
- #444 and #245 remain validation lanes;
- #200 / #201 / #202 remain hardware/validation evidence lanes;
- #189 remains blocked on controlled actual-host recovery evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized by Issue #607.
