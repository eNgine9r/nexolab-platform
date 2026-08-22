# NEXOLAB State Model v2

## Purpose

State Model v2 keeps NEXOLAB resumable from an offline repository checkout without forcing a second reconciliation Pull Request after every successful product merge.

The model separates **durable repository state** from **volatile GitHub observations**.

## Durable state contract

`.project/ACTIVE_SPRINT.json` uses `schema_version: 2` and owns:

- project/profile identity;
- Sprint and execution policy;
- `baselines.accepted_product_sha`;
- `baselines.deployed_product_sha`;
- active/next Work Package intent;
- Work Package lifecycle and exact-head evidence;
- hardware evidence SHA where real hardware acceptance exists;
- maintenance actions;
- safety boundaries.

`.project/LAST_CHECKPOINT.json` uses the same baseline and safety semantics and records a resumable execution point.

Durable state must never require internet access to validate.

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

`verified_head_sha` is the exact Pull Request head to which review and CI results apply.

Repository-side completion requires `verified_head_sha` evidence. It does **not** require a future squash merge SHA.

## Normal Work Package lifecycle

```text
select Issue
→ feature branch
→ targeted implementation
→ targeted checks
→ coherent PR candidate
→ exact-head review/CI/hardware evidence
→ record durable evidence/checkpoint when material
→ GREEN merge
→ query GitHub for merge result
→ delta Ready audit
→ next Work Package
```

Do not create a dedicated post-merge state Issue/branch/PR solely to update `main` SHA, merge SHA or Issue closure.

A state-only PR remains appropriate when Sprint intent, blockers, evidence, baselines, maintenance or state schema changes materially.

## Local tooling

Validate the canonical repository state:

```bash
python3 scripts/project-state.py validate
```

Preview v1 migration without writing:

```bash
python3 scripts/project-state.py migrate-v1 \
  --observed-at 2026-08-22T11:02:23Z \
  --dry-run
```

Select a Work Package:

```bash
python3 scripts/project-state.py begin \
  --issue 650 \
  --title "Introduce State Model v2" \
  --branch chore/650-state-model-v2 \
  --dry-run
```

Record exact-head evidence:

```bash
python3 scripts/project-state.py record-evidence \
  --issue 650 \
  --verified-head-sha <40-char-sha> \
  --pull-request <number> \
  --check core_ci=PASS \
  --check merge_gate=PASS \
  --dry-run
```

Complete repository-side evidence before merge:

```bash
python3 scripts/project-state.py complete \
  --issue 650 \
  --dry-run
```

Create a deterministic checkpoint:

```bash
python3 scripts/project-state.py checkpoint \
  --event issue_650_exact_head_green \
  --next-action "Merge GREEN PR and start delta Ready audit." \
  --timestamp 2026-08-22T12:00:00Z \
  --dry-run
```

All timestamps are explicit inputs. The tooling does not silently use wall-clock time, GitHub APIs or network services.

## Validation invariants

Validation fails closed when:

- schema/project/profile identity is wrong;
- accepted/deployed SHA is not a lowercase 40-character Git SHA;
- duplicate Issues exist;
- selected active Issue is absent or not `in_progress`;
- verification policy is weakened;
- a volatile `repository_main_sha`, `merge_sha` or equivalent field is reintroduced outside `observations`;
- Modbus/hardware write state is not `none`;
- production cutover is represented as authorized;
- canonical JSON formatting is broken.

## Migration policy

The v1 → v2 migration:

- preserves accepted/deployed baselines;
- preserves final verified PR heads;
- preserves hardware evidence SHAs;
- preserves CI/review evidence;
- preserves maintenance deadlines and safety state;
- converts historical merge SHAs into timestamped GitHub observations;
- drops `last_reconciled_repository_sha` / current-main invariants.

Migration is deterministic for the same input documents and explicit `--observed-at` value.

## CI

Genuine changes restricted to the four canonical `.project` files continue to use the state-only fast lane proven by Issue #648 / PR #649.

State-tooling, schema, validator or governance changes are not state-only and must receive the broader CI-governance verification matrix.
