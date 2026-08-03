# NEXOLAB Blockers

Updated: 2026-08-03

## Hard blockers

No hard blocker prevents merging Issue #241 / PR #244 after the final state-only exact-head sweep.

Stop before:

- destructive database or persistent-volume operations;
- restore over production data without isolated proof and explicit approval;
- production/site cutover without explicit approval;
- Modbus or unsafe hardware writes;
- secret exposure or unauthorized key rotation;
- unresolved materially different product or architecture decisions;
- any operation that cannot preserve local laboratory data.

## Active production dependency risks

### N-037 — Transitive `sharp 0.34.5` advisory

**Status:** Remediation and 11-of-11 verification sweep GREEN; pending final state-only checks and merge.

- baseline path: `next@16.2.12 -> sharp@0.34.5`;
- affected range: `<0.35.0`;
- candidate: evidence-backed npm override to `sharp 0.35.3`;
- production audit no longer contains `sharp` or `next` entries;
- linux/x64 native processing passed with libvips `8.18.3`;
- linux/arm64 glibc/musl package integrity is present in the lockfile;
- actual Raspberry Pi execution remains unverified;
- reassess and remove the override when a supported Next.js range is available.

### N-038 — Playwright `1.55.0` dev-tool advisory

**Status:** Open and isolated under Issue #204. It is not a mandatory runtime dependency and is out of scope for PR #244.

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

Merge PR #244 after exact-head GREEN. Continue Issue #203 with Issue #242 (optional Supabase isolation), followed independently by Issue #243 (Lucide operator semantics). Keep Issue #204 isolated.
