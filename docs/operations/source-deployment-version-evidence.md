# Trusted version evidence for controlled source deployments

## Purpose

NEXOLAB may be deployed to the controlled Raspberry Pi directly from the repository with `scripts/deploy-current-head-raspberry-pi.sh`. That deployment has an exact Git commit and runtime evidence, but it is **not** a validated offline package release.

The GitHub-aware update plane needs the deployed source commit to evaluate repository lineage. It must not invent a package identity or treat a later bundle built from the same commit as proof of the exact running artifacts.

`scripts/nexolab-adopt-source-deployment.py` records a bounded source-lineage `current.json` only after verifying the deployed repository and live runtime. The record is explicitly marked:

```text
deployment_authority=controlled_source_deployment
known_packaged_release=false
```

This is lineage evidence only. It is not update/rollback activation authority.

## Safety contract

The adopter is read-only with respect to NEXOLAB runtime, PostgreSQL, MQTT, Device Agent and industrial equipment. It writes only version-management metadata under the configured version-management state root.

Before writing `current.json` it requires:

- canonical origin `eNgine9r/nexolab-platform`;
- branch `main`;
- no tracked working-tree changes;
- valid local `HEAD` and `origin/main` revisions;
- deployed `HEAD` to be a fast-forward ancestor of the existing `origin/main` ref;
- deployment evidence under `runtime/deployments/**`;
- `summary.txt` containing `DEPLOYMENT PASSED`;
- `final-state.txt` commit exactly equal to repository `HEAD`;
- runtime mode matching `runtime/runtime-mode`;
- controlled authentication (`AUTH_MODE` must not be disabled);
- local-auth evidence consistent with the Dashboard auth provider;
- one repository Alembic head and the live database at that same revision;
- Telemetry API, database and MQTT readiness;
- healthy Device Agent bus-worker invariant and telemetry-attempt evidence;
- host platform supported by NEXOLAB.

`origin/main` is allowed to be newer than the deployed `HEAD`; that is the normal state in which update discovery needs trustworthy current lineage. A non-fast-forward relationship fails closed.

Any mismatch fails closed before the metadata record is created.

The adopter does **not**:

- create or validate a package catalog entry;
- stage a bundle;
- enqueue update or rollback;
- restart NEXOLAB;
- mutate PostgreSQL or edge SQLite;
- delete named volumes or product data;
- perform Modbus/controller/hardware writes;
- enable automatic updates.

## Controlled adoption command

Run only after the source deployment itself has completed and its evidence directory is known:

```bash
cd ~/nexolab-platform

sudo python3 scripts/nexolab-adopt-source-deployment.py \
  --root /var/lib/nexolab/version-management \
  --repo "$PWD" \
  --evidence-dir runtime/deployments/<deployment-timestamp>
```

A successful result reports the exact source commit, runtime mode, platform, schema head, runtime health and evidence path. It also reports `known_packaged_release=false`.

If the same verified source deployment has already been recorded, the command is idempotent. A later verified source deployment may replace an older source-lineage record while retaining previous source commit/evidence references. If `current.json` represents a validated packaged release, the adopter refuses to replace it.

## Expected update-plane behavior after adoption

When the deployed source commit still equals `origin/main`, a manual update check may truthfully report:

```text
result_code=up_to_date
current_commit=<deployed-sha>
target_commit=<same-sha>
activation_eligible=false
```

When `origin/main` later advances, discovery may verify fast-forward lineage and the required successful push `CI` for the target. Activation must still remain blocked until the current and target package authority required by the normal version-manager contract exists. A source adoption record is intentionally not sufficient to pass `known_packaged_release` / `current_release_unverified` gates.

The browser and Telemetry Service therefore remain unable to turn a source-lineage record into update authority.

## Automatic-update policy

Source adoption does not change `/var/lib/nexolab/version-management/update-policy.json`.

For a new/uninitialized installation, automatic updates remain OFF. The host timer remains fixed at 02:00 local time, and policy OFF means the scheduled worker exits before GitHub discovery or runtime mutation.

## Recovery and future packaged deployment

Do not hand-edit `current.json` to convert a source deployment into a packaged release.

When NEXOLAB is later installed through an exact staged validated package, the canonical version-manager package flow becomes authoritative. A source-lineage record must never be hand-edited or passed through `bootstrap` to manufacture packaged authority.

The explicit transition is:

```bash
sudo python3 scripts/nexolab-version-manager.py establish-package-authority \
  --root /var/lib/nexolab/version-management \
  --bundle-id <exact-staged-bundle-id> \
  --central-env /etc/nexolab/central.env \
  --edge-env /etc/nexolab/edge.env \
  --backup-dir /var/backups/nexolab \
  --local-auth
```

It accepts only the exact staged validated package whose `source_commit`, host
platform, schema, runtime and local-auth contracts match the verified source
deployment. The package carries the hardware/bridge/standalone runtime overlays
needed by the accepted Raspberry Pi topology. The transition holds both the host
worker lock and update-plane lock, verifies capacity and PostgreSQL backup,
snapshots persistent-volume identities, performs a rollback-aware handoff from the
source systemd Dashboard to the packaged Dashboard, runs the existing offline
installer, revalidates the package marker and manifest, requires exactly one
expected Alembic head, proves real Modbus requests on the same stable
`/dev/serial/by-id/...` topology, checks advancing telemetry, and requires identical
volume identities afterward.

Only then may catalog-backed packaged `current.json` replace the source record.
The packaged record persists hardware authority and its verified RS-485 contract;
subsequent update and rollback operations must keep the hardware overlay and
re-prove that contract before committing `ready`. The previous source commit and
deployment evidence remain auditable. Any pre-install failure preserves the source
record unchanged. A failure after installation starts preserves source-lineage
authority but marks runtime state unverified; when Dashboard handoff began, the
packaged Dashboard is stopped and the source Dashboard is restored.

For legacy controlled-source records that do not yet carry the explicit Dashboard
and auth identity fields, the transition may derive them only from the referenced
immutable `runtime/deployments/**/final-state.txt` evidence. The evidence must remain
under that deployment-evidence root and must match both the exact recorded source
commit and runtime mode. A mismatch or missing fact fails closed rather than
rewriting the legacy record.

Actual execution on the controlled Raspberry Pi is a cutover action and remains
separate from software verification. Preserve source deployment evidence, package
validation markers, operation history and PostgreSQL backups for audit and
recovery.
