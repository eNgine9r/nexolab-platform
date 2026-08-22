# NEXOLAB Current State

Updated: 2026-08-22

## State Model v2 boundary

NEXOLAB continuity uses durable repository state plus current GitHub observations. GitHub remains authoritative for current `main` HEAD, Issue/PR lifecycle, merge SHA and repository settings; those volatile facts do not require a dedicated reconciliation PR.

## Durable baselines

Accepted product source: `6d223415deebf1a44bb52ba4fcaa3c5db9b03697`.

Deployed product source: `6e387485b68fb862d9f82ae7f6000b1f5b672764`.

These identities remain distinct from repository `main`, governance-only commits and the currently unaccepted #618 candidate.

## Completed process hardening — Issue #650

Issue #650 — **Introduce State Model v2 and remove mandatory post-merge reconciliation PRs** — completed through PR #651.

Exact accepted repository-side evidence:

- final PR head `b0c7ae3efbb7a0364c7b6d59a356e858afe74be2`;
- Core CI `32571068430`: PASS;
- Telemetry service `32571068439`: PASS;
- `NEXOLAB Merge Gate`: PASS;
- unresolved review threads: zero;
- GitHub recorded squash merge `2112c1004cdcbf08631b71ad48c7a59a930ec77f` at 2026-08-22T11:57:40Z.

No separate reconciliation PR was created. This #618 material state update ingests the historical #650 evidence as intended by State Model v2.

## Active Work Package — Issue #618

Issue #618 — **Restore Saved Dashboard CSV export browser acceptance on LOCAL_LAN** — is active in branch `fix/618-saved-dashboard-csv-download`.

Repository-backed diagnosis:

- the CSV API client already performs the authenticated local GET with the selected UTC range and browser timezone and parses `Content-Disposition` / CSV content;
- the production E2E already registers `page.waitForEvent("download")` before clicking `Export CSV`, so the known failure is not a simple Playwright listener-order race;
- the browser handoff fetched the Blob, created a detached `<a>`, clicked it and synchronously revoked the Blob URL;
- Chromium may commit the download asynchronously, so immediate revocation can invalidate the handoff before the browser download manager observes it.

Current implementation candidate:

- introduces a small browser-download helper in `src/features/live-dashboards/`;
- appends the download anchor to the DOM during click;
- removes the anchor immediately after click;
- keeps the Blob URL alive for a bounded 1 second before revocation;
- includes a deterministic unit regression proving DOM presence during click and delayed URL revocation;
- `DashboardLiveView` delegates the authenticated Blob handoff to this helper.

The existing `Authenticated Dashboard Acceptance` workflow is path-triggered by these changes and runs the production Chromium / acquisition-invariant stack, including `e2e/live.production.e2e.ts`. That workflow is the required software/browser acceptance for the candidate.

## Runtime and hardware boundary

`nexolab-edge-01` is currently offline in the Remote Desktop connector. Therefore the historical Raspberry Pi LOCAL_LAN failure cannot yet be re-run on the actual host.

This is a soft evidence blocker only: GitHub-hosted production Chromium acceptance can verify the software/browser contract. Final real Raspberry Pi confirmation remains **hardware/runtime unverified** until the host is reachable again.

No Modbus or hardware write is required by #618.

## Current blocker boundary

Issue #646 remains soft-blocked only on repository settings: the latest retained observation reports `main` unprotected with required status checks disabled, and the connected GitHub tool surface does not expose branch-protection/rules mutation.

Security maintenance remains time-bounded: four temporary `CVE-2026-14456` exceptions from Issue #598 are due for review/removal by **2026-08-26**, or earlier if a fixed Debian package becomes available or reachability assumptions change.

Known dependencies remain:

- #607 — next queued architecture lane, dual RS-485 KK1/KK2 isolation;
- #589 blocked on #607;
- #590 blocked on #589;
- #585 blocked pending explicit physical W2 / Unit 201 handback approval;
- #444 and #245 remain validation lanes;
- #200 / #201 / #202 remain hardware/validation evidence lanes;
- #189 remains blocked on controlled actual-host recovery evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized by Issue #618.
