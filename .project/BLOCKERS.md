# NEXOLAB Blockers

Updated: 2026-08-02

## Hard blockers

No hard blocker prevents completing Issue #237 / PR #238 after final exact-head CI and review audit.

Stop before:

- destructive database or persistent-volume operations;
- restore over production data without isolated proof and explicit approval;
- production/site cutover without explicit approval;
- Modbus or other unsafe hardware writes;
- secret exposure or unauthorized signing-key rotation;
- an unresolved materially different product or architecture decision;
- any operation that cannot preserve local laboratory data.

## Completed CI maintenance

### N-021 — GitHub Actions runtime dependencies — resolved through PR #234 / `99c3785f073f37e9c4c131ca68b4c6df3c219114`

The controlled 26-workflow runtime upgrade is merged. All permanent workflows passed on the final implementation sweep, trust boundaries remained unchanged, checkout credentials are not persisted and implicit setup-node package-manager caching is disabled.

## Active DR scripting defect

### N-036 — Generated DR object-storage credential can begin with `-`

**Status:** Software fix verified on the implementation head; pending PR #238 merge.

Resolution:

- generated MinIO credentials receive a fixed `nxl_` prefix at the generator boundary;
- the random `token_urlsafe(36)` payload remains intact;
- the shared Compose credential contract remains unchanged;
- deterministic payload `-leading-option-like` is tested;
- CI `30760710838` is GREEN;
- Disaster Recovery Acceptance `30760710828` completed policy and encrypted restore GREEN on its first attempt;
- sanitized evidence artifact `8837371547` contains no secret material.

## Issue #189 recovery status

Software backup, encrypted restore and rollback evidence is verified. Actual-host and physical recovery remain soft-blocked pending controlled central-host and Raspberry Pi access:

- central-host reboot;
- Raspberry Pi reboot;
- edge power interruption and SQLite outbox recovery;
- physical power-loss behavior;
- actual disk-full/disk-loss behavior;
- operator-owned physical-media restore.

## Open operational and hardware risks

- **N-023 — Node health/status durability:** not claimed to have the same process-restart durability as telemetry measurements.
- **N-024 — Rollback compatibility:** preserve named volumes and do not roll back across incompatible spool schemas.
- **N-025 — Spool capacity policy:** actual-host capacity and throughput evidence remains required.
- **N-032 — ARM64 offline evidence:** full archive/load/start/update/rollback execution on an actual Raspberry Pi 5 remains unverified.
- **N-014 / #200 — Physical RS-485 topology:** hardware blocked; read-only evidence required.
- **N-015 / #201 — LE-01MP cumulative energy:** hardware blocked; display/load correlation required.
- **N-016 / #202 — Extended XJP60D semantics:** hardware blocked; representative KK1/KK2 evidence required.
- **N-017 / #17 — Versioned device profiles:** blocked until #200–#202 evidence exists.

## Next Ready Work Package

After PR #238 merges, execute Issue #203 as a separate focused production-dependency review. Keep major frontend migrations in Issue #204 and hardware work blocked until controlled physical access exists.
