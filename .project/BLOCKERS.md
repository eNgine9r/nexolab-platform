# NEXOLAB Blockers

Updated: 2026-08-07

## Ready audit result

The post-Issue #357 repository audit found one stale control-plane classification and one missing focused Work Package.

### Issue #245 — validation track, not software Ready

Issue #245 no longer carries `status:ready` and is now `status:needs-validation`.

Reason:

- PR #246 already merged the standalone runtime software scope as `83b161ca7e26580c46789e76a7bbdc0d5e434c21`;
- exact-head software CI, Telemetry Service and Offline Bundle evidence was GREEN;
- the latest physical Raspberry Pi evidence records standalone deployment blocked on actual-host runtime health before loopback-only reboot/observation acceptance could be completed.

Current classification:

```text
software verified; actual standalone Raspberry Pi acceptance blocked on actual-host runtime health
```

Do not create a second software implementation branch for #245. Resume it only as a controlled hardware/runtime validation track once the recorded actual-host health blocker is addressed.

### Issue #289 — needs validation

Issue #289 remains `status:needs-validation`, priority critical.

All declared dependencies #283, #284, #285, #286, #287, #314 and #288 are closed. However, #289 measures route-return latency and duplicate request counts that are intentionally affected by the remaining Epic #356 navigation optimization work. Run its final route/performance matrix after Issue #366 and the subsequent route-prefetch/time-to-usable slice so acceptance targets the completed navigation architecture.

This sequencing does not authorize any Modbus/hardware write or change the physical polling envelope.

## Selected Ready Work Package

Issue #366 — **Audit and deduplicate monitoring-route read models** — is the sole executable open `status:ready` Work Package after reconciliation.

No known blocker prevents software work on #366.

Boundaries:

- reuse #314 shared telemetry state and #357 refrigeration structural state;
- no duplicate telemetry cache;
- no route prefetch in this slice;
- no backend/schema expansion without a separately proven gap and explicit scope update;
- no acquisition registry/scheduler/polling changes;
- no dependency upgrades;
- no Modbus/hardware writes;
- no destructive data operation or site cutover.

## Toolchain lanes

Issue #257 remains blocked until the resolved Next.js ESLint plugin graph supports ESLint 10 without broad rule weakening.

Issue #256 remains deferred until TypeScript 7 support is confirmed across Next.js, Vitest/Vite and ESLint integration boundaries.

## Dependency lanes

Open unselected dependency PRs: #340, #341 and #346.

PR #347 remains obsolete because Playwright 1.62 already merged through Issue #254 / PR #352.

These dependency PRs must not interrupt Issue #366 unless a separate dependency Work Package is selected after the product-visible sequence.

## Remaining physical acceptance

- Issue #355: `software verified; Raspberry Pi runtime latency acceptance pending`.
- Issue #357: `software verified; Raspberry Pi perceived-latency acceptance pending`.
- Issue #245: actual standalone Raspberry Pi acceptance blocked on recorded actual-host runtime health.
- Issue #289: hardware performance acceptance pending.
- Issues #189, #200, #201 and #202 remain hardware-dependent according to their existing evidence boundaries.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Do not broaden it.

`/lockers`, physical cameras, ONVIF/RTSP and NVR remain blocked or unverified by their existing evidence requirements.

## Global hard-stop rules

Stop before destructive data or volume operations, production cutover, hardware writes, secret exposure, mandatory online runtime dependencies, grouped migrations or unsupported physical acceptance claims.
