# Work Package: <operator or user outcome>

## Problem

Describe verified behavior and separate facts from assumptions.

## Outcome

Describe the complete operator, laboratory or system result. Avoid defining the task as only a page or component change.

## Current behavior

- ...

## Expected behavior

- ...

## Scope

Include all required layers for the vertical slice where relevant:

- UI and user states;
- API/domain logic;
- data and migrations;
- telemetry/device contract;
- deployment and operations;
- diagnostics, backup and recovery.

## Out of scope

- ...

## Dependencies

- Issue / ADR / hardware / credential / environment dependency

## Permitted directories

```text
src/...
services/...
infrastructure/...
docs/...
```

Changes outside these paths require a documented dependency reason.

## Offline and safety constraints

- Core runtime must not require internet or a paid service.
- No CDN, cloud font or hidden external API dependency.
- No Modbus write operation.
- No production/site cutover unless explicitly scoped and approved.
- Missing real-hardware evidence is reported as unverified, not passed.

## Acceptance criteria

- [ ] ...
- [ ] ...

## Verification commands

### Targeted

```text
<fast checks for touched modules>
```

### Completion

```text
<module tests, lint, typecheck, compile, config validation>
```

### Offline/runtime evidence

```text
<offline startup, local data, hardware simulator/real device, backup and rollback checks>
```

## Blocker policy

- Record a soft blocker and continue with another independent Ready task.
- Stop on hardware-risk, destructive, production-critical or data-preservation hard blockers.

## Definition of Done

- [ ] Acceptance criteria met.
- [ ] Tests added or updated.
- [ ] Required checks actually passed.
- [ ] Offline/safety impact documented.
- [ ] Focused Pull Request linked to the Issue.
- [ ] `.project/CURRENT_STATE.md` updated.
- [ ] `.project/LAST_CHECKPOINT.json` written.
- [ ] Risks and next Ready Work Package recorded.
