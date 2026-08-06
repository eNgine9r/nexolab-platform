# NEXOLAB Architecture Decision Records

This directory is the authoritative registry and canonical storage location for NEXOLAB Architecture Decision Records (ADRs).

## Registry

| ID   | Title                                                       | Status                           | Date       | Supersedes | Canonical record                                                                   |
| ---- | ----------------------------------------------------------- | -------------------------------- | ---------- | ---------- | ---------------------------------------------------------------------------------- |
| 0001 | Central telemetry ingestion architecture                    | Accepted for M2 implementation   | 2026-07-23 | —          | [0001-central-telemetry-ingestion.md](0001-central-telemetry-ingestion.md)         |
| 0004 | Controlled central deployment topology                      | Accepted                         | 2026-07-23 | —          | [0004-central-deployment-topology.md](0004-central-deployment-topology.md)         |
| 0005 | Laboratory test session domain                              | Accepted                         | 2026-07-24 | —          | [0005-laboratory-test-session-domain.md](0005-laboratory-test-session-domain.md)   |
| 0008 | Durable local staging between MQTT and PostgreSQL           | Proposed in Issue #198 / PR #207 | 2026-08-01 | —          | [0008-durable-central-ingestion-spool.md](0008-durable-central-ingestion-spool.md) |
| 0009 | Local operator authentication for disconnected laboratories | Accepted                         | 2026-08-01 | —          | [0009-local-operator-authentication.md](0009-local-operator-authentication.md)     |

Every canonical ADR must appear exactly once in this table. An ADR identifier is permanent after publication, including when the decision is later superseded.

## Historical numbering gaps

The repository contains no ADR documents or Git history evidence that assigns the following identifiers. They remain unassigned historical gaps; no decision content is inferred for them.

| ID   | Classification            | Evidence                                                                   |
| ---- | ------------------------- | -------------------------------------------------------------------------- |
| 0002 | Unassigned historical gap | No ADR file or supported repository evidence found during Issue #300 audit |
| 0003 | Unassigned historical gap | No ADR file or supported repository evidence found during Issue #300 audit |
| 0006 | Unassigned historical gap | No ADR file or supported repository evidence found during Issue #300 audit |
| 0007 | Unassigned historical gap | No ADR file or supported repository evidence found during Issue #300 audit |

Do not backfill or reuse these identifiers. The next ADR must use the next unused identifier after the highest published ADR unless an accepted governance decision explicitly changes this rule.

## Filename and content convention

New ADRs use:

```text
docs/adr/NNNN-lowercase-kebab-case-title.md
```

Required document fields:

```markdown
# ADR NNNN: Decision title

- Status: Proposed | Accepted | Deprecated | Superseded
- Date: YYYY-MM-DD
```

Existing published heading and status formatting is preserved. The integrity validator recognizes the current historical formats but new ADRs must use the convention above.

Allowed lifecycle statuses are:

- `Proposed`;
- `Accepted`;
- `Deprecated`;
- `Superseded`.

When an ADR is superseded:

1. keep its identifier and canonical file;
2. change its status to `Superseded`;
3. name the replacing ADR in the document and in the registry `Supersedes` relationship;
4. do not rewrite the original decision history.

## ADR-0001 compatibility path

ADR-0001 was originally published at:

```text
docs/architecture/adr-0001-telemetry-ingestion.md
```

That path remains as an explicit compatibility pointer to the canonical record:

[ADR-0001: Central telemetry ingestion architecture](0001-central-telemetry-ingestion.md)

Do not delete the compatibility file or duplicate decision content there.

## Integrity validation

Run:

```bash
python3 scripts/validate-adr-registry.py
python3 -m unittest tests.test_adr_registry -v
```

The validator fails when:

- two canonical ADR files claim the same identifier;
- a registry identifier is duplicated;
- a canonical ADR is absent from the registry;
- a registry target is missing or points to a different ADR identifier;
- a canonical filename or heading identifier is invalid;
- ADR-0001's legacy compatibility path is missing or does not target the canonical file;
- a registry or compatibility Markdown link is broken;
- a historical gap overlaps a published ADR or is undocumented.
