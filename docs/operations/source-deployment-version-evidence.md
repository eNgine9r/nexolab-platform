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
- local `HEAD` exactly equal to the existing `origin/main` ref;
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

If `current.json` already represents a validated packaged release, the adopter refuses to replace it.

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

When NEXOLAB is later installed through an exact staged validated package, the canonical version-manager package flow becomes authoritative. Any transition from source-lineage evidence to packaged current-release evidence must be implemented and verified explicitly; it must not overwrite trustworthy current state merely to make an update button available.

Preserve source deployment evidence, package validation markers, operation history and PostgreSQL backups for audit and recovery.
