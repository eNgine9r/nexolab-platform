# NEXOLAB Blockers

Updated: 2026-08-13

## Issue #369 — product acceptance passed, merge gates pending

Issue #369 / PR #420 has completed the mandatory real Raspberry Pi browser
acceptance for the canonical Live Dashboard inventory.

Physical browser evidence:

```text
inventory_http_status=200
inventory_total=162
inventory_duration_ms~=44.84
search=PASS
filter=PASS
select_two_channels=PASS
reorder=PASS
configuration_valid=YES
save=PASS
reopen=PASS
telemetry_latest_inventory_dependency=NO
```

Automated gates on the pre-state head
`d037b732a8ae87a8d9f79f31cffeddde01a5eec9` were GREEN:

- CI #2961;
- Authenticated Dashboard Acceptance #1640;
- Offline Bundle #1023.

No hardware acceptance blocker remains for #369. The remaining merge blocker is
procedural: the `.project` reconciliation changes the PR head, so the resulting
exact head must pass required checks before Ready transition and merge.

## Non-blocking browser-console observation

The acceptance screenshots show repeated `404 Not Found` requests for equipment
`.../layout/published` resources, including examples for `showcase-107-02` and
`cold-room-201`.

These requests are outside the Live Dashboard inventory path and did not affect
#369 search/filter/select/reorder/save/reopen behavior. They are recorded as an
observation, not misclassified as a #369 failure and not silently described as a
clean console.

No corrective change for those layout requests is included in PR #420.

## Issue #366 — dependency blocked until #369 merge

Issue #366 remains `status:blocked` while #369 is unmerged. After #369 merges, run
a repository-backed dependency and Ready audit before changing #366 status or
starting implementation.

Preserved runtime sequence:

```text
#369 -> #366 -> #289
```

## Issue #389 — independent Ready package

Issue #389 remains `status:ready` for administrator-only local Version
Management. It is independent of #369, but must not be selected until the
post-merge Ready audit confirms priority and dependencies.

## Other known boundaries

- Issue #415 remains an open Chart System UX follow-up.
- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked by ESLint 10 ecosystem compatibility.
- Issue #256 remains deferred pending TypeScript 7 ecosystem compatibility.
- `max_parallel_implementation_tasks` remains 1.

## Security boundary

The `telemetry-service/libcjson1/CVE-2026-67216` exception expires on
**2026-09-05**. Issue #369 does not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus
or other hardware writes, secret exposure, mandatory online runtime dependencies,
privileged hardware containers or unsupported physical-acceptance claims.
