# Raspberry Pi GitHub-aware updates

This runbook describes the optional GitHub-aware maintenance plane for NEXOLAB `LOCAL_LAN` Raspberry Pi deployments.

## Runtime boundary

GitHub is **not** part of the core monitoring runtime. Loss of internet, DNS or GitHub must not stop local authentication, Dashboard/API access, PostgreSQL, MQTT, Device Agent acquisition or local telemetry history.

The update plane is allowed to use internet only when an operator requests discovery or when the host-local 02:00 scheduler runs with automatic updates enabled.

The browser never executes shell commands and never receives a GitHub token or host credential.

## Automatic-update policy

The persisted host policy defaults to **OFF** on an uninitialized installation.

When enabled, the host uses `nexolab-update-check.timer` with:

```ini
OnCalendar=*-*-* 02:00:00
Persistent=false
```

Therefore:

- one automatic attempt is scheduled daily at 02:00 Raspberry Pi local time;
- timezone/DST handling remains host-local through systemd;
- a missed 02:00 window does not trigger an unexpected daytime catch-up after boot;
- when policy is OFF, the scheduled worker exits before GitHub/network discovery and performs no runtime mutation;
- manual `Перевірити оновлення зараз` remains available while automatic updates are OFF.

## Discovery and eligibility

A newer `origin/main` commit is only a discovery candidate. It is **not** installation authority.

Before activation can become eligible, the host verifies:

1. configured origin is exactly `eNgine9r/nexolab-platform`;
2. checked-out branch is `main`;
3. tracked working tree is clean;
4. deployed source revision is known;
5. target is fast-forward reachable from deployed lineage;
6. exact target SHA has a completed successful `CI` workflow from a `push` to `main`;
7. current release has validated local package evidence;
8. an exact matching target package already exists in the validated local catalog;
9. target platform matches the installed platform;
10. schema upgrade compatibility is explicitly declared;
11. no update/rollback operation is already active or queued.

Typical non-destructive blocked states include:

- `github_unavailable`;
- `repository_mismatch`;
- `branch_mismatch`;
- `tracked_worktree_dirty`;
- `non_fast_forward`;
- `ci_not_green` / `ci_pending_or_missing`;
- `current_release_unverified`;
- `validated_package_required`;
- `platform_incompatible`;
- `schema_compatibility_unknown`;
- `operation_in_progress`.

A failed discovery/eligibility gate does not restart NEXOLAB or mutate persistent product data.

## Manual update

In **Settings → System Version**:

1. select `Перевірити оновлення зараз`;
2. inspect current and target commit/package evidence;
3. if the target is eligible, select the validated target package;
4. choose Update;
5. enter the exact confirmation phrase shown by the UI, e.g. `APPLY <bundle-id>`;
6. submit once.

The authenticated backend revalidates authorization and package identity before queuing the existing privileged version-manager operation.

Rollback uses the same control plane and exact confirmation form `ROLLBACK <bundle-id>`.

## Automatic 02:00 activation

When automatic updates are enabled and an eligible target exists, the scheduled host actor is recorded as:

```text
system:update-timer
```

The scheduler revalidates the candidate and writes the normal version-manager request/operation evidence. It does not use a second deployment path.

Automatic activation is blocked if another update/rollback is queued or running.

## Runtime mutation gates

Before package installation starts, the privileged version manager performs the same bounded safety sequence:

1. validate current and target package evidence;
2. validate platform and schema compatibility;
3. run deployment-capacity preflight;
4. create and validate a PostgreSQL backup;
5. apply the validated offline package with pull disabled;
6. verify database revision and local runtime readiness;
7. when edge runtime is in scope, verify Device Agent `expected_bus_workers == active_bus_workers`, `workers_healthy=true`, and advancing local telemetry attempt evidence.

Capacity or backup failure occurs before package mutation and therefore must fail closed without changing the current runtime.

## Progress and reconnect behavior

The UI reports durable phases instead of invented percentages:

```text
Перевірка пакета
→ Перевірка вільного місця
→ Створення резервної копії
→ Застосування
→ Перевірка локального runtime
→ Готово
```

During an expected Dashboard/API restart the already-rendered page remains tied to the same durable operation ID. A temporary local disconnect is not interpreted as a second update request.

Success is shown only after host verification completes. Failures retain the failed phase, safe reason and available capacity/backup evidence identifiers.

## Offline behavior

With internet/GitHub unavailable:

- monitoring continues normally;
- manual update discovery reports an explicit update-plane unavailable state;
- automatic discovery skips/fails non-destructively;
- local validated offline package update and rollback remain separate from GitHub discovery;
- no cloud fallback or Supabase requirement is introduced for `LOCAL_LAN`.

## Host installation

The versioned offline bundle contains:

- `nexolab-version-manager.py`;
- `nexolab-update-orchestrator.py`;
- `deploy-capacity-guard.sh`;
- version-manager systemd units;
- update-check/request systemd units.

`deploy-version-manager-service.sh` installs these host workers and enables the paths/timer. It does **not** run an update or GitHub discovery by itself. Automatic-update policy remains OFF until explicitly enabled by an administrator.

## Evidence

Keep evidence under the version-management state root and deployment evidence directories. Do not copy secrets, passwords, bearer tokens, private keys or production telemetry payloads into Git or Pull Requests.

Important evidence includes:

- update-check current/target commit and blocked/eligible reason;
- validated package identity;
- durable operation ID and actor;
- capacity report identifier;
- PostgreSQL backup identifier;
- operation phase/result;
- Device Agent worker/freshness verification when edge runtime is in scope.

## Prohibited actions

Do not use the update workflow to perform:

- Modbus/controller writes;
- hardware/actuator writes;
- `docker compose down -v`;
- named-volume or product-data deletion;
- persistent PostgreSQL/SQLite/MinIO/MQTT reset;
- browser-to-shell execution;
- arbitrary feature-branch deployment;
- mandatory cloud runtime migration;
- production/site cutover without a separately approved Work Package.

## Raspberry Pi acceptance

Software/CI evidence does not replace real Raspberry Pi acceptance. A controlled deployment of the merged implementation requires separate approval and must record exact target SHA, Dashboard/API readiness, Device Agent worker health, telemetry advancement, local authentication continuity and rollback/recovery evidence as scoped by the acceptance Work Package.
