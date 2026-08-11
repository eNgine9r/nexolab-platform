# NEXOLAB Blockers

Updated: 2026-08-07

## Resolved recovery blockers

### Issue #378 — resolved and merged

Issue #378 / PR #380 is completed. Final exact head `5635df201a6cbd59227a8ebe181c44fa5167f67c` completed 14 checks with 0 failures and 0 in-progress, and PR #380 squash-merged as `6645af46a198ff454142df3b0a713984f4d71196`.

Controlled Raspberry Pi hotplug acceptance passed on the same running Device Agent across `/dev/ttyUSB1 -> /dev/ttyUSB0` re-enumeration with restart count `0 -> 0` and resumed PostgreSQL telemetry.

The RS-485 USB re-enumeration blocker is no longer active.

### Issue #374 — regression parent resolved

Issue #374 / PR #375 remains a valid merged partial fix. Its later USB re-enumeration regression is resolved by Issue #378 and same-container hardware evidence. It is not a current sequencing blocker.

### Issue #381 — state reconciliation completed

Issue #381 is closed completed through PR #382 / merge `329282496491d2ee27ab4f292e982a30af33c2b7`. It must not remain listed as an active or sequencing blocker.

## Issue #368 — active validation track

Issue #368 / PR #373 is the selected critical Work Package.

The previously frozen software candidate is:

```text
105ae34425a8937a6f61c172b52ce2c6fa09f3b3
26 completed checks
0 failures
0 in-progress
0 queued
```

That result was exact for a branch reconciled through `main` at `329282496491d2ee27ab4f292e982a30af33c2b7`.

Current `main` advanced to `72f32d387e0199f7b863a56931d40a411ebf999c` through documentation-only Chart System PR #384. Therefore the older #368 CI result is not the final pre-hardware gate. Before Raspberry Pi migration-v2:

- reconcile PR #373 with current `main`;
- rerun full exact-head CI;
- freeze the new exact candidate;
- recheck Raspberry Pi schema, acquisition freshness and advisory-lock state;
- create a fresh database backup and checksum;
- only then execute controlled migration-v2/latest-query acceptance.

This is a sequencing/verification requirement, not a new hardware defect.

## Runtime sequencing

- #368 is active and must complete current-main reconciliation, exact-head CI and controlled physical acceptance.
- #369 waits for #368 physical migration/latest-query acceptance.
- #366 waits for the #368 -> #369 runtime acceptance sequence.
- #289 remains downstream after #366.
- #245 remains a separate Raspberry Pi validation track.
- #257 remains blocked by ESLint 10 compatibility.
- #256 remains deferred pending TypeScript 7 ecosystem compatibility.

## Prepared Ready backlog

Issue #385 — local Raspberry Pi user administration and role management — is Ready but not selected.

Issue #386 — chart-domain primitives and local renderer benchmark — is Ready but not selected.

The Sprint allows one active implementation task. Neither #385 nor #386 should start in parallel while #368 occupies that slot unless the Product Owner explicitly changes priority or #368 becomes blocked and the repository selection policy promotes an independent package.

## Chart System status

Issue #383 / PR #384 is completed and merged. There is no active chart-spec blocker.

Future chart implementation still requires:

- #386 shared chart-domain primitives and renderer benchmark;
- later route-by-route migrations;
- real Raspberry Pi performance and acquisition-invariant acceptance before claiming hardware verification.

No chart hardware acceptance has been performed yet.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Do not broaden it.

## Global hard-stop rules

Stop before destructive data or volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, grouped migrations, privileged hardware containers or unsupported physical acceptance claims.
