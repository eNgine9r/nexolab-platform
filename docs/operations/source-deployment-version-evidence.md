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
- valid local `HEAD` and `origin/main` revisions with the control checkout remaining on `main`;
- control `HEAD` to be a fast-forward ancestor of the existing `origin/main` ref;
- deployment evidence under `runtime/deployments/**`;
- `summary.txt` containing `DEPLOYMENT PASSED`;
- a valid deployment-evidence source commit that exists in Git and remains in canonical `main` lineage;
- for normal current-main deployments, evidence source equal to control `HEAD`;
- for explicit historical-main deployments, `requested_source_ref`, `expected_deployed_source` and `control_origin_main` evidence bound to the deployed source and canonical control-main ancestry;
- runtime mode matching `runtime/runtime-mode`;
- controlled authentication (`AUTH_MODE` must not be disabled);
- local-auth evidence consistent with the Dashboard auth provider;
- one Alembic head derived from the exact deployment-evidence source commit through Git object inspection, and the live database at that same revision;
- Telemetry API, database and MQTT readiness;
- healthy Device Agent bus-worker invariant and telemetry-attempt evidence;
- host platform supported by NEXOLAB.

`origin/main` is allowed to be newer than the deployed source. For an explicit historical-main deployment, the repository stays/restores on canonical control `main`; the adopter verifies the evidence commit independently, derives build/schema identity from that commit using Git objects, verifies the evidence control-main ancestry up to current `HEAD`/`origin/main`, and never checks out or moves a Git ref. A non-fast-forward or unbound historical relationship fails closed.

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

## Explicitly approved historical-main deployment

The normal controlled source deployment still targets current `origin/main`. When a Product Owner-approved runtime fix must stop at an earlier commit because later `main` commits contain unrelated unapproved production scope, use the bounded historical-main mode rather than rewriting Git refs or deploying a feature branch.

Preflight the exact lineage first:

```bash
bash scripts/deploy-current-head-raspberry-pi.sh \
  --runtime-mode lan \
  --source-ref <approved-target-40-sha> \
  --expected-deployed-source <current-deployed-40-sha> \
  --source-selection-check-only
```

The real deployment uses the same two SHA arguments without `--source-selection-check-only`. The supplied deployed source must match authoritative successful source-deployment evidence (`DEPLOYMENT PASSED` plus a valid `commit=` in `final-state.txt`). Authority ordering uses the immutable-format UTC evidence directory stamp (`YYYYMMDDTHHMMSSZ`), not mutable filesystem `mtime`. Before retention runs, the matching active successful evidence path is resolved and passed as an explicit protected directory. Retention canonicalizes the deployment root, current audit directory and protected evidence path before comparison so a repository path reached through a host symlink cannot falsely reject the same physical evidence directory. A later attempt whose evidence shows `runtime-mutation-started` (or a legacy equivalent mutation log) but lacks a later successful completion makes deployed-source authority indeterminate and the historical operation fails closed. The target must then be a fast-forward descendant of that deployed source and an ancestor of freshly fetched `origin/main`. The no-runtime preflight itself fetches and fast-forwards to fresh `origin/main` before validating lineage. The repository must start clean on `main`; feature-only commits, malformed SHA values, downgrades and divergent commits fail closed before product-runtime mutation. The script temporarily detaches only after capacity and source-authority gates pass and restores the repository to the captured `origin/main` head on both success and failure. It never moves `origin/main` or another remote ref.

Deployment evidence records `commit`, `requested_source_ref`, `expected_deployed_source`, `expected_deployed_evidence` and `control_origin_main` separately so a bounded historical source deployment cannot be mistaken for current-main deployment. Immediately before the first runtime-mutating Compose activation, the attempt also writes `runtime-mutation-started`; a later failed attempt carrying this marker blocks future historical source authority until recovery or a later successful deployment establishes a new trusted state. This mode is a production/site-cutover operation and still requires an explicitly approved Work Package.

## Controlled adoption command

Run only after the source deployment itself has completed and its evidence directory is known:

```bash
cd ~/nexolab-platform

sudo python3 scripts/nexolab-adopt-source-deployment.py \
  --root /var/lib/nexolab/version-management \
  --repo "$PWD" \
  --evidence-dir runtime/deployments/<deployment-timestamp>
```

Before writing version-management metadata, the adopter requires the supplied evidence directory to be the latest authoritative successful source deployment by validated UTC directory stamp. A later failed attempt that crossed the explicit `runtime-mutation-started` boundary (or a legacy equivalent mutation log) makes authority indeterminate and adoption fails closed; a later pre-mutation failure does not replace the last successful authority. If `current.json` already carries controlled-source authority, the candidate source commit must also be the same revision or a fast-forward descendant of that existing source commit, even when the existing evidence directory has been removed by retention. This independently prevents stale successful evidence from moving source authority backward.

A successful result reports the exact deployed source commit, runtime mode, platform, source-commit Alembic head, runtime health and evidence path. For a historical-main runtime this deployed source may intentionally differ from repository `HEAD`; `current.json` records that distinction with `source_historical_main`, the control checkout/origin commits and the deployment-evidence control-main commit. It also reports `known_packaged_release=false`.

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
deployment. If the source deployment predates the recovery tooling, the bundle is
built from the current clean tooling checkout with
`--runtime-source-ref <deployed-source-sha>`: runtime images and schema are taken
from that exact source tree, while installer/overlay tooling is taken from the
current checkout. Digest-bound provenance records a distinct `tooling_commit` and
required split-runtime capability evidence, preventing an old source revision from
silently supplying incompatible recovery tooling. The package carries the
hardware/bridge/standalone runtime overlays needed by the accepted Raspberry Pi
topology. The transition holds both the host
worker lock and update-plane lock, loads the verified manifest image references
into the Compose environment before any backup command, verifies capacity and
PostgreSQL backup, snapshots persistent-volume identities, performs a rollback-aware handoff from the
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
