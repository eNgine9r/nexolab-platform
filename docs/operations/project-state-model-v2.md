# NEXOLAB State Model v2

## Purpose

State Model v2 keeps NEXOLAB resumable from an offline repository checkout without forcing a second reconciliation Pull Request after every successful product merge.

The model separates **durable repository state** from **volatile GitHub observations** and uses one dependency-free repository writer for canonical state transitions.

## Durable state contract

`.project/ACTIVE_SPRINT.json` uses `schema_version: 2` and owns:

- project/profile identity;
- Sprint and execution policy;
- `baselines.accepted_product_sha`;
- `baselines.deployed_product_sha`;
- active/next Work Package intent;
- Work Package lifecycle and dependency information;
- exact-head evidence already known and safe to anchor;
- hardware evidence SHA where real hardware acceptance exists;
- maintenance actions;
- safety boundaries.

`.project/LAST_CHECKPOINT.json` uses the same baseline and safety semantics and records a resumable execution point.

Durable state must validate without internet access.

## Work Package lifecycle

The supported lifecycle values are:

```text
queued
ready
in_progress
review
completed
blocked
needs_validation
hardware_validation
```

Normal autonomous execution is:

```text
ready
→ in_progress
→ review
→ completed
```

A soft implementation failure may transition:

```text
in_progress → blocked
```

A blocked/validation item may return to `ready` only after the blocker or validation boundary is explicitly resolved. The Sprint Runner does not silently unblock work.

The selected active Work Package may be `in_progress` or `review`. WIP remains one: after a successful Codex run reaches `review`, Team Lead review is required before another Work Package starts. After a soft failure is recorded as `blocked`, an independent Ready package may continue.

Dependencies are Issue numbers under `depends_on` and must reference known Work Packages. Autonomous execution requires dependencies to be `completed`.

## Volatile GitHub observations

These facts are not durable invariants:

- current `main` HEAD;
- current Issue state;
- current PR state;
- squash merge SHA;
- branch-protection/rules state.

GitHub is authoritative for them when online.

A repository snapshot may preserve one under:

```json
{
  "source": "github",
  "observed_at": "2026-08-22T11:02:23Z",
  "kind": "historical_merge",
  "data": {
    "issue": 648,
    "pull_request": 649,
    "merge_sha": "..."
  }
}
```

An observation is historical evidence only. It is not an invariant that requires a later state commit when GitHub changes.

## Evidence identities

Use distinct identities:

```text
accepted_product_sha
deployed_product_sha
verified_head_sha
hardware_evidence_sha
```

`verified_head_sha` is an exact Pull Request head to which review/CI evidence applies. Evidence fields are append-once/immutable: replaying the same value is idempotent, while attempting to replace an existing evidence anchor with a different value fails closed.

Repository-side completion requires a verified head plus recorded check evidence. It does **not** require a future squash merge SHA.

### Avoid exact-head self-reference

A PR cannot safely write its own final head SHA into a file inside that same PR after CI: the state commit itself would create another head and invalidate the value just recorded.

Therefore:

- final exact-head CI/review results for the currently open PR remain authoritative in GitHub;
- do not add a commit merely to copy the just-produced final head/run IDs into the same PR;
- a later **material** state/planning change may ingest that historical evidence while beginning the next Work Package;
- do not create a dedicated post-merge reconciliation Issue/branch/PR solely for that ingestion.

This preserves exact-head truth without recreating the self-referential state cycle that v2 removes.

## Normal Work Package lifecycle

```text
select Ready Issue
→ feature branch
→ targeted implementation
→ targeted checks
→ coherent PR candidate
→ exact-head review/CI/hardware evidence
→ GREEN merge
→ query GitHub for merge result
→ delta Ready audit
→ next Work Package
```

A state-only PR remains appropriate when Sprint intent, blockers, accepted/deployed baselines, maintenance data or the state schema materially changes.

## Canonical local writer

Use `scripts/project-state.py` for canonical state mutations. It validates the full repository state before any v2 mutation and writes JSON atomically.

Validate:

```bash
python3 scripts/project-state.py validate
```

Preview v1 migration:

```bash
python3 scripts/project-state.py migrate-v1 \
  --observed-at 2026-08-22T11:02:23Z \
  --dry-run
```

Begin an existing Ready Work Package:

```bash
python3 scripts/project-state.py begin \
  --issue 650 \
  --title "Introduce State Model v2" \
  --branch chore/650-state-model-v2 \
  --dry-run
```

Transition lifecycle explicitly:

```bash
python3 scripts/project-state.py transition \
  --issue 650 \
  --to review \
  --dry-run
```

Record exact-head evidence when it can be anchored without self-reference:

```bash
python3 scripts/project-state.py record-evidence \
  --issue 650 \
  --verified-head-sha <40-char-sha> \
  --pull-request <number> \
  --check core_ci=PASS \
  --check merge_gate=PASS \
  --dry-run
```

Complete repository-side evidence:

```bash
python3 scripts/project-state.py complete \
  --issue 650 \
  --dry-run
```

Create a deterministic checkpoint:

```bash
python3 scripts/project-state.py checkpoint \
  --event issue_650_review \
  --next-action "Review exact-head CI and merge only when GREEN." \
  --timestamp 2026-08-22T12:00:00Z \
  --dry-run
```

All timestamps are explicit inputs. The tooling does not silently use wall-clock time, GitHub APIs or network services.

## Autonomous Sprint Runner

`scripts/ai-sprint-run.ps1` is a consumer of State Model v2, not a second JSON writer.

It:

- validates v2 before reading the queue;
- reads `work_packages` and `lifecycle`;
- selects only `ready` work;
- requires declared dependencies to be `completed`;
- delegates `begin`, lifecycle transitions and checkpoints to `scripts/project-state.py`;
- never writes a schema-v1 checkpoint;
- stops after a successful Work Package reaches `review` so Team Lead review preserves WIP=1;
- may continue to another independent Ready package after a soft failure is recorded as `blocked`.

## Validation invariants

Validation fails closed when:

- schema/project/profile identity is wrong;
- accepted/deployed SHA is not a lowercase 40-character Git SHA;
- duplicate Issues exist;
- dependencies are missing, self-referential or malformed;
- selected active Issue is absent or not `in_progress`/`review`;
- verification policy is weakened;
- a volatile repository-main or merge-SHA equivalent is reintroduced outside `observations`;
- evidence/check structures are malformed;
- Modbus/hardware write state is not `none`;
- production cutover is represented as authorized;
- canonical JSON formatting is broken.

Mutation tooling additionally fails closed when:

- an existing Work Package is begun without lifecycle `ready`;
- a lifecycle transition is not explicitly allowed;
- an existing evidence anchor is replaced with a different value;
- completion lacks verified-head or check evidence;
- the repository/checkpoint is malformed before mutation.

## Migration policy

The v1 → v2 migration:

- preserves accepted/deployed baselines;
- preserves final verified PR heads;
- preserves hardware evidence SHAs;
- preserves scalar verification/review evidence;
- preserves optional scope, verification and dependency metadata where available;
- preserves maintenance deadlines and safety state;
- converts historical merge SHAs into timestamped GitHub observations;
- drops `last_reconciled_repository_sha` / current-main invariants.

Migration is deterministic for the same input documents and explicit `--observed-at` value.

## CI

Genuine changes restricted to the four canonical `.project` files continue to use the state-only fast lane proven by Issue #648 / PR #649.

State-tooling, schema, Sprint Runner, validator or governance changes are not state-only and must receive the broader CI-governance verification matrix.
