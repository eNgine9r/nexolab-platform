# NEXOLAB Blockers

Updated: 2026-08-02

## Hard blockers

No hard blocker prevents completing Issue #239 / PR #240 after final exact-head CI and review audit.

Stop before:

- destructive database or persistent-volume operations;
- restore over production data without isolated proof and explicit approval;
- production/site cutover without explicit approval;
- Modbus or unsafe hardware writes;
- secret exposure or unauthorized key rotation;
- unresolved materially different product or architecture decisions;
- any operation that cannot preserve local laboratory data.

## Resolved reliability defect

### N-036 — Generated DR credential can begin with `-` — resolved

PR #238 merged as `36b63cd6aba96c0fcb0e7f8649496e0207840cf3`. The generator adds `nxl_`, preserves entropy and passed first-attempt encrypted restore.

## Active production dependency risks

### N-037 — Transitive `sharp 0.34.5` advisory

**Status:** Open risk; separate focused Work Package required after PR #240.

- artifact `8837927439` resolves `sharp` to `0.34.5`;
- the advisory affects `<0.35.0`;
- Next.js `16.2.12` declares optional `sharp` as `^0.34.5`;
- direct Next.js advisories affecting `<16.2.11` are removed;
- do not force an unsupported override inside PR #240.

### N-038 — Playwright `1.55.0` dev-tool advisory

**Status:** Open but out of scope for Issue #239.

It is not a mandatory runtime dependency and belongs to the separate toolchain track.

## Issue #189 recovery status

Software recovery evidence is verified. Actual-host and physical recovery remain soft-blocked pending controlled central-host and Raspberry Pi access.

## Open operational and hardware risks

- **N-023 — Node health/status durability:** not claimed equal to telemetry process-restart durability.
- **N-024 — Rollback compatibility:** preserve named volumes and spool compatibility.
- **N-025 — Spool capacity:** actual-host capacity evidence remains required.
- **N-032 — ARM64 offline evidence:** actual Raspberry Pi 5 archive/load/start/update/rollback remains unverified.
- **N-014 / #200 — Physical RS-485 topology:** hardware blocked.
- **N-015 / #201 — LE-01MP cumulative energy:** hardware blocked.
- **N-016 / #202 — Extended XJP60D semantics:** hardware blocked.
- **N-017 / #17 — Versioned profiles:** blocked until #200–#202 evidence exists.

## Next Ready Work Package

Merge PR #240 after exact-head GREEN. Create a separate focused Issue for N-037 (`sharp`). Then review Supabase and Lucide independently under parent Issue #203. Keep Issue #204 isolated.
