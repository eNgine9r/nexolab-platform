# NEXOLAB Blockers

Updated: 2026-08-02

## Hard blockers

No hard blocker prevents completing and merging Issue #197.

Stop before:

- destructive database or persistent-volume operation;
- restore over production data without an isolated proof and explicit approval;
- production/site cutover without explicit approval;
- Modbus or other unsafe hardware write;
- secret exposure or unauthorized signing-key rotation;
- an unresolved materially different product or architecture decision;
- inability to preserve local laboratory data.

## Issue #189 recovery status

### N-012A — Software backup, restore and rollback evidence

**Status:** Verified and merged through PR #224 as `f54cd7b6f6db580f3931a40889f5b4e33af3cc30`.

### N-012B — Actual-host and physical recovery evidence

**Status:** Soft blocker; Issue #189 remains open.

The following require controlled central-host and Raspberry Pi access and remain unverified:

- central-host reboot;
- Raspberry Pi reboot;
- edge power interruption and SQLite outbox recovery;
- physical power-loss behavior;
- actual disk-full/disk-loss behavior;
- operator-owned physical-media restore.

Do not claim these from container or CI evidence.

## Formatting maintenance status

### N-033 — Historical Prettier debt inventory

**Status:** Resolved by Issue #191 / PR #192.

Verified baseline:

- exact debt: 46 files;
- Prettier: `3.9.6`;
- generated/vendor candidates: 0;
- justified new `.prettierignore` exclusions: 0.

### N-034 — Controlled formatting child sequence

**Status:** Final child in progress.

Completed:

- Issue #193 / PR #225 — 3 documentation files;
- Issue #194 / PR #226 — 6 E2E/root tooling files;
- Issue #195 / PR #227 — 10 telemetry/dashboard files;
- Issue #196 / PR #228 — 10 refrigeration domain/repository files, merged as `402df05d516af08f1d001e3b80bcb174c33197e0`.

Issue #197 / PR #229 is formatting-only and pending final exact-head CI after project-state updates.

Verified Issue #197 evidence:

- exact scope: 17 refrigeration UI/component paths;
- initial fail-closed semantic workflow `30749791642` stopped before source commit;
- diagnostic workflow `30749858956`, artifact `8834080073`, digest `sha256:85967a8a6039585559511bccc86c1d053e2e51432ddff17faf1030693ae0f727`;
- verified semantic workflow `30749965825`, artifact `8834113947`, digest `sha256:b79c4aa42a7a6bbeec9de6f0f45a228794ce46e8c6ac22c8610839c6731c822f`;
- staging workflow `30750064883` passed exact artifact hash and allowlist checks;
- TSX structural AST, JSX text slots, direct `className` utility-token sets and exact comment sequences remained identical;
- targeted catalog, detail, layout editor and sensor-placement tests passed;
- all 17 patches were reviewed;
- ARIA labels, visible text, icons, coordinates, handlers, conditions and assertions are unchanged;
- clean commit `35fc2d51c5b6d1c794c81cc1488e97a73043e683` was created directly from merged `main` using only verified formatted blob SHA values;
- final source diff contains exactly the 17 allowlisted files before mandatory state updates;
- all temporary diagnostic/evidence/staging workflows are absent from final branch history and diff.

No product redesign, defect fix, refactor, dependency, runtime, deployment, hardware or Modbus change is included.

After #197, zero paths remain in the 46-file historical formatting inventory.

## Next Ready Work Package

### Parent Issue #185 — Final Prettier zero-difference verification

**Status:** Ready after PR #229 merge.

Run locked repository-wide Prettier verification, prove zero remaining differences, update project state and close parent #185. Do not mix dependency, feature, refactor or deployment work into the closure gate.

## Open operational and hardware risks

### N-023 — Node health/status durability

Current node health/status persistence is not claimed to have the same process-restart durability as telemetry measurements.

### N-024 — Rollback compatibility

Do not roll back to a pre-ADR-0008 image while pending or terminal spool records exist. Preserve named volumes and never use the volume-removal flag during update or rollback.

### N-025 — Spool capacity policy

Software thresholds and alerts exist. Validate them against actual-host capacity and throughput evidence. Never auto-delete pending or terminal records.

### N-032 — ARM64 and operator-host offline evidence

The bundle contract supports `linux/arm64`, but complete archive/load/start/update/rollback execution on an actual Raspberry Pi 5 or operator-owned disconnected host remains unverified.

## Other open soft blockers

- **N-031 / Issue #210 evidence — Affected-PC session bootstrap:** actual host/network cause remains unverified.
- **N-014 / #200 — Physical RS-485 topology:** hardware blocked; read-only evidence required.
- **N-015 / #201 — LE-01MP cumulative energy:** hardware blocked; display/load correlation required.
- **N-016 / #202 — Extended XJP60D semantics:** hardware blocked; representative KK1/KK2 evidence required.
- **N-017 / #17 — Versioned device profiles:** blocked until #200–#202 evidence exists.
- **N-018 / #108 — Optional Tailscale acceptance:** requires controlled hosts.
- **N-019 / #203 — Production dependency updates:** queued maintenance.
- **N-020 / #204 — Major frontend toolchain:** queued maintenance.
- **N-021 / #205 — GitHub Actions runtime dependencies:** queued maintenance.

Missing actual-host or hardware evidence remains unverified. A green software, disconnected-container or scanner result does not authorize image publication, hardware write or site deployment.
