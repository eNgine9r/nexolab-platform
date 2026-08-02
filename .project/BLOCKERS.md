# NEXOLAB Blockers

Updated: 2026-08-02

## Hard blockers

No hard blocker prevents completing Issue #205 / PR #234 after the final exact-head workflow sweep is GREEN.

Stop before:

- destructive database or persistent-volume operations;
- restore over production data without isolated proof and explicit approval;
- production/site cutover without explicit approval;
- Modbus or other unsafe hardware writes;
- secret exposure or unauthorized signing-key rotation;
- an unresolved materially different product or architecture decision;
- any operation that cannot preserve local laboratory data.

## Active GitHub Actions maintenance

### N-021 — GitHub Actions runtime dependencies

**Status:** Verified on the implementation head; final exact-head sweep pending after mandatory state updates.

Issue #205 / PR #234 upgrades the supported action runtime majors across exactly 26 permanent workflows. The reviewed matrix is:

- `actions/checkout@v4` → `@v6`;
- `actions/setup-node@v4` → `@v6`;
- `actions/setup-python@v5` → `@v7`;
- `actions/upload-artifact@v4` → `@v7`;
- `actions/download-artifact@v4` → `@v8`;
- Docker QEMU, Buildx and login actions `@v3` → `@v4`;
- `docker/metadata-action@v5` → `@v6`;
- `docker/build-push-action@v6` → `@v7`.

Security and compatibility constraints remain intact:

- every permanent checkout sets `persist-credentials: false`;
- setup-node implicit package-manager caching is disabled explicitly;
- existing explicit npm cache declarations remain unchanged;
- no `pull_request_target`, `workflow_run` or self-hosted runner is introduced;
- workflow permissions, trusted/untrusted trigger boundaries, refs, fetch depth, paths, runner labels and secrets references are not broadened;
- no npm, Python, container or product dependency is upgraded.

Implementation-head evidence for `7a072f4ff5d64c19d6a857f3838cac54c4be247c`:

- 26 of 26 permanent workflows completed GREEN after targeted reruns;
- CI, Security Browser Acceptance, Refrigeration Browser Acceptance, Disaster Recovery Browser and Offline Bundle are GREEN;
- Offline Auth Acceptance and Disaster Recovery Acceptance both passed on targeted rerun;
- no action download, Node 24 action-runtime or GitHub-hosted runner compatibility failure was observed.

### N-036 — Generated DR object-storage credential can begin with `-`

**Status:** Open soft blocker tracked by Issue #237; not part of the action-runtime change.

Disaster Recovery Acceptance run `30755039014` initially failed because a randomly generated disposable MinIO credential began with `-` and was interpreted by the MinIO client as a CLI option. The targeted rerun passed with a different generated value.

This is a real pre-existing nondeterministic scripting defect. It must not be hidden by retry and must be fixed in a separate focused Work Package with a deterministic leading-hyphen regression test. It does not justify mixing DR script changes into PR #234.

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

Do not claim these outcomes from container or CI evidence.

## Completed formatting maintenance

Issues #185 and #230 are closed. The permanent repository-wide Prettier 3.9.6 gate is merged through PR #233 as `e1e0e2311d1818157e3326ae9ca67adbf24813d5`, and the historical 46-file formatting backlog is zero.

## Existing test-output risks

The full frontend suite remains GREEN but emits pre-existing warnings:

- React state updates not wrapped in `act(...)` in several tests;
- non-boolean attributes reaching mocked DOM elements;
- duplicate React keys in one temperature-chart fixture.

These warnings remain outside Issue #205 and require a separate focused test-quality Work Package.

## Open operational and hardware risks

- **N-023 — Node health/status durability:** not claimed to have the same process-restart durability as telemetry measurements.
- **N-024 — Rollback compatibility:** do not roll back to a pre-ADR-0008 image while pending or terminal spool records exist; preserve named volumes.
- **N-025 — Spool capacity policy:** actual-host capacity and throughput evidence remains required; never auto-delete pending or terminal records.
- **N-032 — ARM64 offline evidence:** complete archive/load/start/update/rollback execution on an actual Raspberry Pi 5 remains unverified.
- **N-031 / Issue #210 — Affected-PC session bootstrap:** actual host/network cause remains unverified.
- **N-014 / #200 — Physical RS-485 topology:** hardware blocked; read-only evidence required.
- **N-015 / #201 — LE-01MP cumulative energy:** hardware blocked; display/load correlation required.
- **N-016 / #202 — Extended XJP60D semantics:** hardware blocked; representative KK1/KK2 evidence required.
- **N-017 / #17 — Versioned device profiles:** blocked until #200–#202 evidence exists.
- **N-018 / #108 — Optional Tailscale acceptance:** requires controlled hosts.
- **N-019 / #203 — Production dependency updates:** ready after current CI maintenance and Issue #237.
- **N-020 / #204 — Major frontend toolchain:** queued maintenance.

Missing actual-host or hardware evidence remains unverified. A green software, disconnected-container or scanner result does not authorize image publication, hardware write or site deployment.

## Next Ready Work Package

After PR #234 reaches final exact-head GREEN and merges, close superseded Dependabot PRs #217–#221 and close Issue #205. Then execute Issue #237 to remove the nondeterministic leading-hyphen DR credential failure. After #237, continue with Issue #203 production dependency review. Hardware work remains blocked until controlled physical access is available.
