# NEXOLAB Current State

Updated: 2026-08-23

## State Model v2 boundary

NEXOLAB continuity uses durable repository state plus current GitHub observations. GitHub remains authoritative for current `main` HEAD, Issue/PR lifecycle and merge SHA; a separate post-merge reconciliation PR is not required merely to copy volatile GitHub facts.

## Durable baselines

Accepted product source: `286a219611f95413b5580d8099a7c5665416d1ad`.

Deployed product source: `6e387485b68fb862d9f82ae7f6000b1f5b672764`.

The accepted product source includes Issue #590 / PR #657 operator acquisition-cadence controls. The Raspberry Pi deployment baseline remains intentionally older and must not be represented as containing #607/#589/#590 or later work until a controlled deployment actually occurs.

## Completed Work Package — Issue #590

Issue #590 — **Add operator acquisition cadence controls to NEXOLAB Settings** — merged through PR #657 as accepted product source `286a219611f95413b5580d8099a7c5665416d1ad`.

Hardware cadence acceptance remains **unverified** because the Remote Desktop/Raspberry Pi connector is offline. No software evidence is represented as physical KK1/KK2 acceptance.

## Completed Work Package — Issue #615

Issue #615 — **Fix authenticated dashboard acceptance Compose project-name generation** — completed through PR #658 and squash-merged to GitHub `main` as `4f76c3683a5a6e47d1a1115c9caa20989d28f8ee`.

Exact implementation evidence is anchored to verified PR head `107935b7ab08ca48878b73603a6d1a9e683985f0`:

- dependency-free project-name regression tests: PASS `3/3` inside Core CI;
- Core CI `32607900557`: PASS — State Model/CI policy, standalone runtime contracts, ADR/dependency policy, format, lint, typecheck, full tests and production build;
- Authenticated Dashboard Acceptance `32607900561`: PASS — the real runner started the authenticated acceptance stack without a manual `COMPOSE_PROJECT_NAME` override and completed dashboard/acquisition-invariant acceptance;
- `NEXOLAB Merge Gate`: PASS;
- unresolved review threads: zero.

Implementation outcome:

- the generated UTC run suffix uses lowercase `t/z` separators accepted by Docker Compose project-name validation;
- explicit caller-provided `COMPOSE_PROJECT_NAME` remains byte-for-byte unchanged;
- PID-based per-run uniqueness remains intact;
- runner functional diff is one line;
- deterministic `test_ci_*.py` coverage executes the real runner bootstrap through project-name export;
- no dashboard acceptance semantics, product runtime, application Compose names, dependency graph, Modbus behavior or hardware behavior changed.

The final PR head `dddb67e7e62f30a0ecfce8f02b89e5ddf7990419` also passed exact-head Core CI `32608239242`, Authenticated Dashboard Acceptance `32608239348` and `NEXOLAB Merge Gate` before merge. Issue #615 is closed with `status:done`.

## Runtime and offline boundary

Issue #615 changes acceptance tooling only and does not alter the deployed NEXOLAB runtime. It introduces no internet/cloud runtime dependency.

The Raspberry Pi connector is online again. The repository checkout on `nexolab-edge-01` was fast-forwarded to GitHub `main` `4f76c3683a5a6e47d1a1115c9caa20989d28f8ee` without restarting or replacing the immutable production dashboard release `6e387485b68fb862d9f82ae7f6000b1f5b672764`.

## Current blocker boundary

- #200: passive hardware evidence is captured, but full topology acceptance is blocked. The host currently enumerates one CP2104 RS-485 adapter only; physical cable topology/termination/biasing/shielding, physical Unit ID 115 presence/absence and two-adapter KK1/KK2 isolation remain unverified.
- #607/#590: the connector is online, but the deployed product source remains `6e387485b68fb862d9f82ae7f6000b1f5b672764`; no controlled deployment of #607/#589/#590 has occurred. Dual-bus hardware acceptance is additionally blocked by the absence of a second enumerated RS-485 adapter.
- #646: technical `main` branch protection remains a soft access blocker; current GitHub observation still reports protection disabled.
- Security maintenance: temporary `CVE-2026-14456` exceptions remain due for review/removal by **2026-08-26** or earlier if fixed packages/reachability assumptions change.
- #585 remains blocked pending explicit physical W2 / Unit 201 handback approval.
- #444 and #245 remain validation lanes.
- #200 / #201 / #202 remain hardware/validation evidence lanes.
- #189 remains blocked on controlled actual-host recovery evidence.

## Hardware validation checkpoint — Issue #200

A passive read-only audit on `nexolab-edge-01` established the current hardware/runtime boundary without starting a second Modbus master:

- one stable adapter is enumerated: `usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_0133F090-if00-port0` -> `/dev/ttyUSB0`;
- production Device Agent uses `9600 8N1`, `0.30 s` timeout and one retry on legacy `rs485-main`;
- persisted acquisition registry revision `10` records XJP60D `102/104/106/108/126`, LE-01MP `200/202/203` active, LE-01MP `201` disabled and the remaining catalog as discovery-only;
- Unit ID `115` is absent from the persisted device and target lists, which proves registry absence only, not physical field absence;
- a passive 60-second window recorded `402` physical requests, `306` successes, `96` timeouts/retries and bus load `75.591% -> 76.942%`; `service_operations` stayed empty.

Sanitized conclusions are recorded in `docs/rs485/issue-200-current-physical-topology.md`; raw runtime snapshots remain ignored under `runtime/evidence/issue-200-passive-20260823T070935Z`. No scanner, Modbus write, service restart, wiring change or cutover occurred.

Issue #200 is therefore blocked on physical topology inspection and/or availability of the intended second isolated adapter.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. Issue #615 authorizes no Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency.
