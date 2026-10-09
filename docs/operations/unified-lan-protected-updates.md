# Unified LAN and Google-protected HTTPS updates

Issue #1313 extends the existing source and offline-package update paths to the
already installed Google gateway. LOCAL_LAN remains the primary, offline runtime.
The optional public interface keeps its Google gate and local application login.

## Source selection and artifacts

Select an exact reviewed commit in canonical `main` after required CI is GREEN.
The source must contain the external image-content contract from PR #1312 and the
gateway-aware tooling from #1313. Production activation needs Product Owner
approval for that exact source and the runtime scope below.

Run `frontend-release-artifact.yml` with `source_ref` set to that full commit and
`external_origin` set to `https://nexolab-edge-01.tail7f9b04.ts.net`. Keep the normal
LAN API/WebSocket inputs. The workflow builds separate linux/arm64 artifacts from
one checkout: the LAN profile and the HTTPS/WSS profile with local authentication
and authenticated image transport. Download and extract each artifact into a
separate directory. Verify their checksum inventories and equal source SHA.

The source deploy command takes the usual approved LAN options plus:

```bash
--frontend-artifact /absolute/path/to/lan-artifact \
--external-frontend-artifact /absolute/path/to/external-artifact \
--external-origin https://nexolab-edge-01.tail7f9b04.ts.net
```

Use `scripts/deploy-current-head-raspberry-pi.sh --help` for the complete command
and expected currently deployed source. The control checkout stays on canonical
`main`; historical source selection must use its explicit approved source-ref
mode. Feature branches are never deployed directly.

Candidates run sequentially on LAN port 3101 and protected port 3102. The active
protected frontend stays on loopback port 3100. Import validates checksums,
source/platform/Node/build/public contracts and archive safety without npm or
network on Pi. The protected candidate retains the 768 MiB kernel memory cap.
An installed gateway without its matching artifact, a changed API upstream,
service override, missing memory controller or occupied candidate port fails
before backend runtime mutation.

Both candidates must prove exact source/build and login readiness. The frontend
handoff preserves the previous LAN identity and protected unit/identity. Failed
frontend activation restores both frontends and verifies the protected previous
identity. This is frontend recovery; backend/database recovery still follows the
existing controlled-deployment runbook. OAuth, NGINX, Funnel and Google account
policy are not changed.

## Establishing package authority

The photograph's historical source record is not a validated package. Never edit
`current.json` to set `known_packaged_release=true`, and never use `bootstrap` to
pretend that a source deployment was installed from an offline bundle.

First complete the approved unified source deployment and read-only source
adoption described in [Source deployment version evidence](source-deployment-version-evidence.md).
The adopter verifies the latest authoritative deployment evidence, database and
Device Agent before updating lineage metadata. LAN and protected frontend source
identities must then match this current record; mixed current identities block a
package transition.

On a connected build host, build **both current and target** offline bundles using
the reviewed tooling, an exact `--runtime-source-ref`, the site's LAN origins and
`--auth-provider local`. For each bundle provide its corresponding exact-source
HTTPS artifact with `--external-frontend-artifact DIR`. Runtime images use the
selected source; installer tooling provenance remains recorded separately. The
bundle contains the HTTPS runtime and fixed provenance files, never the site
environment or Google credentials. Its manifest and package inventory bind the
external source, build, origin, organization and checksums.

Alternatively, dispatch `offline-bundle.yml` on reviewed canonical tooling with
the exact `runtime_source_ref`, `platform=linux/arm64`, the LAN origins,
`auth_provider=local` and the optional `external_origin` above. The workflow
builds the protected artifact in a clean detached worktree at the selected runtime
SHA, then includes it in the verified bundle. Generated CI configuration stays in
the tooling checkout; it cannot contaminate the frontend source. Protected
versions/artifact names receive a `-protected` suffix. Empty `external_origin`
keeps the existing LAN-only build and CI behavior.

The selected runtime must include the #1315 Dashboard Dockerfile fix that creates
and copies `public` even when the source has no public assets. Older runtime
Dockerfiles omit that directory and fail frontend artifact export; do not reuse
the failed run `37892179879` or treat its successful Next compilation as a usable
release. Build current and target packages sequentially on `main`, because the
workflow's per-ref concurrency cancels an earlier in-progress run.

Verify each bundle, transfer it locally, and stage it with the version manager.
Install the reviewed version-manager service/tooling using
`scripts/deploy-version-manager-service.sh`, preserving existing site environment
files. This privileged installation is part of the approved host activation.
Then use the established backup/volume-preserving handoff from
[Local version management](local-version-management.md), for example:

```bash
sudo python3 /usr/local/lib/nexolab/nexolab-version-manager.py \
  establish-package-authority \
  --root /var/lib/nexolab/version-management \
  --bundle-id CURRENT_VALIDATED_BUNDLE_ID \
  --source-repo /home/nexolab/nexolab-platform \
  --central-env /etc/nexolab/central.env \
  --edge-env /etc/nexolab/edge.env \
  --backup-dir /var/backups/nexolab \
  --local-auth
```

Review the actual installed environment paths before execution; the command is a
template, not approval for the production transition. It prepares the external
candidate before backup/runtime mutation, verifies both runtime identities and
preserved volumes, and grants package authority only after readiness evidence.
Failure restores the protected unit; source-transition recovery also verifies
the source runtime. Failed recovery leaves authority unknown.

Normal package update and rollback use the same external transaction. A legacy
package without the HTTPS artifact cannot activate on a host with the protected
frontend installed. After a failed package runtime mutation, the current record
remains `verification_failed`/unknown even when the external unit was restored;
frontend restoration alone does not prove backend/database recovery.

## Operator acceptance

PostgreSQL backup clients now use one policy inside their database container:
512 MiB of virtual address space, 600 seconds of CPU time, a 900-second wall-clock
timeout with a ten-second kill grace, and lower CPU/I/O priority. The host worker
also bounds its Docker invocation. These are client limits; database-server
resources are unchanged. Missing tools or unsupported limits fail closed.
Container environment overrides may only shorten the reviewed time limits or
lower the memory ceiling; zero, unlimited and larger values are rejected.
Archive listing has its own 60-second container timeout. Failed, empty or invalid
backups retain private partial files and diagnostics and stop before mutation;
only an archive passing `pg_restore --list` is promoted. This listing checks
archive structure, and does not replace restore testing.

Capacity measurement uses the same bounded dump policy, reuses its successful
process-local measurement, and falls back to a conservative database-size
estimate on measurement failure. New bundle provenance advertises
`bounded-postgresql-backup`; its client policy must be in the checksum inventory.
Install the corresponding reviewed worker/tooling before repeating an interrupted
installation. An inert limit probe is not evidence of a successful full backup
or a diagnosis of a host freeze.

Settings → System Version displays the actual frontend commit/build for the
current link separately from the update record. A mismatch warns the operator and
blocks activation. Unpackaged source authority gives an explicit package setup
explanation and disables installation/rollback. Discovery of a newer GREEN GitHub
revision alone is not activation authority.

After approved activation, verify these journeys on both LAN and HTTPS:

- Current frontend source/build matches the selected release and update authority.
- Staged target installation, backup evidence and phase progression complete.
- Reload still shows the verified target; rollback reaches the verified prior
  package on both interfaces while preserving data and named volumes.
- Anonymous API, WebSocket upgrade, image-content and Device Agent paths return
  denial; browser navigation reaches the existing Google sign-in gate.
- Google permitted/denied-account and full-session-expiry checks are separately
  exercised with authorized accounts. Anonymous probes do not prove those flows.
- Telemetry advances and worker health remains ready; no hardware writes occur.

Source/unit tests, local production builds and CI do not establish this actual-host
acceptance. Record the exact source, both builds, artifact hashes, deployment and
package operation evidence before closing the Work Package.
