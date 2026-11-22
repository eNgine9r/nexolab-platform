# XWEB Advanced Chart System — consolidated owner-run release runbook

**Status: prepared, NOT executed, NOT an authorisation.** Everything here is for the Product Owner to run on the site, one explicit decision per phase. An agent must not run any privileged command, backup, restore, migration or activation on the site. Nothing in this repository has been installed on edge-01 by this programme.

**Release readiness signal (`🟢 Оновлюйся`): WITHHELD.** The project's own criteria (`.project/ACTIVE_SPRINT.json` → `operator_update_readiness_signal`) require confirmed data preservation and backup protection, a verified rollback path and no unresolved release gate. Section 3 lists what is satisfied and what is not; the remaining items need the owner's physical equipment and decisions.

## 1. Verified release identity

| Item                                                | Value                                                                                                                                                                                                                           |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Runtime source (all product code)                   | `7db6e1a801aa6c1a142febd4e91c79eef62d5beb` (`main`)                                                                                                                                                                             |
| Offline bundle tooling                              | `90fb6e34ae5febc4596c913faa7fbb458bb5d0ed`                                                                                                                                                                                      |
| **Offline bundle (linux/arm64)**                    | run `45048496700`; archive `nexolab-offline-recovery-7db6e1a801aa-tooling-90fb6e34ae5f-protected-arm64.tar.gz`, 804 209 778 bytes                                                                                               |
| Bundle archive SHA-256                              | `1c1ec6d4b3578d19538438f2545c44e6745a11fd771c08b23a4ca9de8c068695` (matches the recorded `.sha256`; GitHub artifact ZIP digest `sha256:3198707d2fa238561a779a6d327cf01a20d6fb54be2edfca9f415bea2f5dcf18`)                       |
| Bundle manifest SHA-256 / images archive            | manifest `a39b8964dd0590f062b5f5b44cb24d70c5debe1a6664561c64ae42b4d1bb415c`; images `0895628a3fe87491ccece769e1dad894da0b8bd3301af652a700cb9f8080585a` (1 763 234 304 bytes)                                                    |
| Bundle schema contract                              | head `20261122_0041`; **`upgrade_from` = `20260908_0037`** (the deployed backend head); `runtime_compatible_schema_heads` = `20261122_0041`; backup required; migration before readiness                                        |
| Bundle verification performed                       | 69/69 `SHA256SUMS`, 68/68 manifest files, images archive hash, the bundle's own `verify-offline-bundle.py` → `verified` (6 images, linux/arm64); no secrets, no network or paid service required; persistent data never deleted |
| Bundle CI proof (disconnected runtime)              | update and rollback preserved all named volumes (identical volume list before/after), local-auth refresh and logout revocation OK, Device Agent healthy with egress blocked                                                     |
| **Do not use** the first bundle (run `45041892083`) | its `upgrade_from` is only `20261122_0041`; the version manager would refuse it on a site at `20260908_0037`                                                                                                                    |
| Standalone LAN frontend artifact                    | `Frontend Release Artifact` run `45041887488`; runtime tarball SHA-256 `50e3e2e11f8819865cdae0c78f6b7844758c679d98a662a80ee19d3569399c52`, build `CWBsCWWebOZGHa5YyWp18`, ZIP digest `sha256:25956ecf88…`                       |
| Standalone protected-HTTPS frontend artifact        | same run; runtime tarball SHA-256 `72218ebf542c969ab307b3af429490ef5389598ed94f09ffbd3af05e55e409ab`, build `fLvuDhT8Ol-bCkGGhHBI4`, ZIP digest `sha256:2db98244…`                                                              |
| Published attested images (ghcr, amd64+arm64)       | device-agent `sha256:a0008cf1…`, telemetry-service `sha256:b3337627…`, telegram-gateway `sha256:53212309…`, mqtt-dynamic-security `sha256:e1bec05d…`, object-storage `sha256:4895db98…` (provenance + SBOM attestations)        |
| Contract of both frontends                          | public contract PASS: LAN `http://172.18.48.66:8082` / `ws://172.18.48.66:8082/api/v1/telemetry/live`; HTTPS `https://nexolab-edge-01.tail7f9b04.ts.net`; auth `local`; ARM64 native binaries                                   |

The standalone frontend artifacts and the bundle's embedded frontends are **separate builds with different build IDs** from the same source. Use one path per surface (section 6) and record the build IDs actually activated.

## 2. What the release changes — exact migration chain

Deployed backend head `20260908_0037` → final head `20261122_0041`. Computed from the Alembic graph of deployed source `ffdefc45` vs the release source; nothing rewritten, no other heads:

```
20260908_0037
 ├─ 20261104_0038  add equipment_commissioning_sessions.display_name (nullable)
 └─ 20261116_0038  live_dashboard_items: node_id/equipment_id, channel_ref_id nullable, check + unique constraint
        └─ 20261116_0039  merge (no-op)
              └─ 20261118_0040  create commissioned_channel_names
                    └─ 20261122_0041  live_dashboards.view_settings (nullable JSON)
```

- Only small operator-configuration tables are touched; **`telemetry_samples` and every other large table are untouched**, so the 19 GB database is not rewritten.
- Rehearsed on an isolated PostgreSQL 16: from `0037` with legacy rows seeded, upgrade to head in 0.09 s, all legacy rows preserved, single head, constraints valid (12/12 checks); also 9/9 scenarios for `0041` including downgrade refusal while operator views exist.
- The **Device Agent is not part of this change** and the site runs a commissioned image (`nexolab/quick-agent:1490`). See stop rule S2.
- The telemetry-service image also carries the CVE-2026-124709 hardening (OpenSSL CLI removed) and the saved-view and registry backend features accumulated since `ffdefc45` (commissioned channel names, observed series, CSV).

## 3. Gate matrix (actual status)

| Gate (from the project's readiness criteria)                 | Status                      | Evidence / what is missing                                                                                                                                                                                                                                                                                                                                                      |
| ------------------------------------------------------------ | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Validated local package for the revision and device platform | **Satisfied**               | Section 1: archive, manifest, 69/69, 68/68, own verifier `verified`, linux/arm64, source `7db6e1a8`                                                                                                                                                                                                                                                                             |
| Source-bound CI and review                                   | **Satisfied**               | All exact-head checks and the Merge Gate green on every merged PR; main-push workflows green on `7db6e1a8`; real-stack saved-view and custom-period acceptance green                                                                                                                                                                                                            |
| Security policy                                              | **Satisfied, time-limited** | Container policy passes on amd64 and arm64 with Product Owner-approved exact exceptions (CVE-2026-124709 until 2026-12-15, tracked in #1692; 18 telemetry exceptions until 2026-11-30). Rebuilds after those dates need renewed decisions                                                                                                                                       |
| Migration chain verified                                     | **Satisfied (isolated)**    | Section 2; no production migration has been run                                                                                                                                                                                                                                                                                                                                 |
| Guarded installation procedure                               | **Ready**                   | This runbook, the read-only preflight (section 4), the leaf runbooks                                                                                                                                                                                                                                                                                                            |
| **Data preservation and backup protection (#1428)**          | **NOT satisfied**           | Tooling merged and rehearsed on synthetic data (leaf A #1630, C #1631, B #1632). **No real backup, off-device copy or independent restore has been done on the site.** Needs the owner's media, key custodians and isolated host                                                                                                                                                |
| **Rollback path verified and available**                     | **Partial**                 | Frontend: previous images/HTTPS release are retained on the Pi as of 2026-11-21 (the preflight re-checks). **Backend after migration: the version manager refuses a managed rollback to the previous package** (its `runtime_compatible_schema_heads` cannot name `0041`); the rollback is a restore from the verified pre-update backup — which is why #1428 gates the backend |
| No unresolved installation or release gate                   | **NOT satisfied**           | #1428; #1606 offline reboot / power-cycle; #1409 / #1399 Docker–LAN network overlap; Pi density measurement; a signed-in owner browser review; real-controller relay/defrost/alarm semantics and the Embraco scale (#1603/#1625)                                                                                                                                                |
| On-host read-only preflight                                  | **NOT done**                | No remote access to the Pi from the agent environment (SSH key not accepted). Only network-level read-only probes were possible (section 4)                                                                                                                                                                                                                                     |

## 4. Phase 0 — read-only preflight (owner-run)

**Observed from the agent environment on 2026-11-22 (read-only HTTP):** LAN frontend `http://172.18.48.66:3000/api/runtime-identity` → source `f02954091bfa3113c2f435b71d8a7189967b4865`, build `PyM62Vg07TywCAwHY6JjL`, identity source `offline_image_manifest` (the #1638 release); `http://172.18.48.66:8082/health/ready` → `status: ready`, database, MQTT ready, ingestion lag 0.09 s, queue 0; the running OpenAPI does **not** contain `view_settings` (backend update needed for saved views); the public HTTPS entrypoint answers `302` (OAuth gate). The Device Agent health port is loopback-only and was not probed.

Run on the Pi (writes nothing; save the output into the release record). It also prints the version-manager evidence (`schema_head`, bundle, `edge_hardware_required`):

```bash
#!/usr/bin/env bash
# NEXOLAB XWEB release - OWNER-RUN, STRICTLY READ-ONLY preflight for the Raspberry Pi.
# Every command below only reads state (docker ps/images/inspect, df, curl GET, systemctl status,
# a single SELECT). It starts, stops, writes, migrates and deletes nothing. A PASS here is NOT
# deployment approval. Save the output and attach it to the release record.
set -u
EXPECTED_DEPLOYED_SOURCE="f02954091bfa3113c2f435b71d8a7189967b4865"   # frontend currently active (#1638)
RELEASE_SOURCE="7db6e1a801aa6c1a142febd4e91c79eef62d5beb"             # release candidate
LAN_UI="http://172.18.48.66:3000"
API="http://172.18.48.66:8082"
fail=0
say() { printf '\n== %s\n' "$*"; }
ok()  { printf 'PASS %s\n' "$*"; }
bad() { printf 'FAIL %s\n' "$*"; fail=1; }
note(){ printf 'INFO %s\n' "$*"; }

say "1. Host capacity (gate: > 20 GiB free on the Docker data root and root filesystem)"
df -h / /var/lib/docker 2>/dev/null
free_kib=$(df --output=avail -k /var/lib/docker 2>/dev/null | tail -1 | tr -d ' ')
[ -n "${free_kib:-}" ] && [ "$free_kib" -gt 20971520 ] && ok "free space > 20 GiB" || bad "free space below 20 GiB or unreadable"
free -h; uptime

say "2. Running containers and images (record IDs: backend IDs must be unchanged after a frontend-only release)"
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.ID}}'
docker images --format 'table {{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}' | head -30

say "3. Active frontend identity (must be the previous release; rollback target)"
ui=$(curl -fsS -m 10 "$LAN_UI/api/runtime-identity" || true); echo "$ui"
echo "$ui" | grep -q "$EXPECTED_DEPLOYED_SOURCE" && ok "LAN frontend runs the expected current source" || bad "LAN frontend source differs from $EXPECTED_DEPLOYED_SOURCE"
for p in 3105 3104 3100; do
  r=$(curl -fsS -m 5 "http://127.0.0.1:$p/api/runtime-identity" 2>/dev/null || true); [ -n "$r" ] && note "127.0.0.1:$p -> $r"
done

say "4. Telemetry API readiness and backend schema gap"
curl -fsS -m 10 "$API/health/ready" && ok "telemetry ready" || bad "telemetry not ready"
if curl -fsS -m 15 "$API/openapi.json" | grep -q '"view_settings"'; then note "running API already exposes view_settings"; else note "running API does NOT expose view_settings (backend update required for saved analysis views)"; fi
note "Alembic revision in the live database (read-only SELECT; adapt the container name if different):"
pg=$(docker ps --format '{{.Names}}' | grep -i postgres | head -1)
[ -n "$pg" ] && docker exec "$pg" sh -c 'psql -U "${POSTGRES_USER:-nexolab}" -d "${POSTGRES_DB:-nexolab}" -Atc "select version_num from alembic_version"' 2>&1 || bad "postgres container not found"
note "main head is 20261122_0041; every revision after the live one would run on a backend update: 20261104_0038, 20261116_0038, 20261116_0039, 20261118_0040, 20261122_0041"

say "4b. Version-manager deployment evidence (the update is only offered when schema_head is in the bundle's upgrade_from)"
VM_ROOT="/var/lib/nexolab/version-management"
if [ -r "$VM_ROOT/current.json" ]; then
  python3 - "$VM_ROOT/current.json" <<'PY'
import json, sys
c = json.load(open(sys.argv[1]))
for key in ("bundle_id", "release", "source_commit", "schema_head", "platform", "runtime_mode"):
    print(f"INFO current.{key} = {c.get(key)}")
print("PASS current schema head is the expected 20260908_0037" if c.get("schema_head") == "20260908_0037"
      else "FAIL current schema head is not 20260908_0037; the bundle's upgrade_from must be rebuilt for it")
hw = c.get("edge_hardware_required") is True
print(f"INFO current.edge_hardware_required = {c.get('edge_hardware_required')}")
print(f"INFO current.hardware_contract present = {isinstance(c.get('hardware_contract'), dict)}")
print("INFO edge hardware authority is packaged: the update keeps the commissioned Device Agent only if this contract is valid; "
      "if edge_hardware_required is not true STOP and review before any update (the stock main agent must never replace nexolab/quick-agent)")
PY
else
  note "cannot read $VM_ROOT/current.json (run this script with the privileges that own it, read-only)"
fi
ls -1 "$VM_ROOT/operations" 2>/dev/null | tail -5

say "5. Device Agent (must NOT be replaced by this release)"
curl -fsS -m 10 http://127.0.0.1:8081/health && ok "device agent healthy" || bad "device agent health unreachable"
docker ps --format '{{.Names}} {{.Image}}' | grep -i agent

say "6. Disaster-recovery gate evidence (#1428) - alarms, not permission"
if [ -x scripts/nexolab-dr-readonly-health.py ] || [ -f scripts/nexolab-dr-readonly-health.py ]; then python3 scripts/nexolab-dr-readonly-health.py || true; else note "run scripts/nexolab-dr-readonly-health.py from the controlled checkout"; fi
note "Required for ANY backend/migration release: a verified complete encrypted OFF-DEVICE backup and an independent isolated restore (#1428). Not provable by this script."

say "7. Gateway and unit state (read-only)"
systemctl --no-pager --type=service --state=running 2>/dev/null | grep -iE "nexolab|nginx|tailscale" || true

say "8. Rollback assets present"
docker images --format '{{.Repository}}:{{.Tag}}' | grep -E "nexolab/dashboard:issue-1638-f0295409-arm64|nexolab/dashboard:issue-1522-469485b0-arm64" || bad "previous dashboard images not found"

say "RESULT"
[ "$fail" -eq 0 ] && echo "PREFLIGHT_READ_ONLY_PASS (informational; not approval)" || echo "PREFLIGHT_READ_ONLY_FAIL (resolve before requesting any release authorisation)"
exit "$fail"
```

Also run, from a checkout at the release commit: `python3 scripts/nexolab-dr-readonly-health.py` (alarms, not permission) and `python3 -I -B scripts/nexolab-site-dr-preflight.py --destination <mounted backup media>`; for the guarded deployment script's read-only source selection: `scripts/deploy-current-head-raspberry-pi.sh --source-ref 7db6e1a801aa6c1a142febd4e91c79eef62d5beb --expected-deployed-source f02954091bfa3113c2f435b71d8a7189967b4865 --source-selection-check-only`.

### Stop rules (any one means STOP and bring the output back)

- **S1** `schema_head` is not `20260908_0037` → the bundle's `upgrade_from` must be rebuilt for the real head (the build input `upgrade_from_schema_heads` exists for this).
- **S2** `edge_hardware_required` is not `true` or the hardware contract is missing, or any plan would recreate the Device Agent container → the commissioned agent must not be replaced.
- **S3** free space below 20 GiB, backend not ready, previous dashboard images missing, or a queued/running version-manager operation.
- **S4** Phase 1 (backup protection) not complete.

## 5. Phase 1 — real backup, off-device copy, independent restore (#1428; owner decisions and equipment required)

Reuse the merged tooling; read each leaf runbook first. Required from the owner: **backup destination** (dedicated USB SSD ≥ 128 GB recommended, or an authorised LAN workstation), **two key custodians and a second key location**, **an isolated host** (spare Pi preferred), and permission for each privileged step.

1. **A — scheduled encrypted complete backup** ([`dr-scheduled-backup-1630.md`](dr-scheduled-backup-1630.md), "Owner-approved site procedure"): create `/etc/nexolab/dr-backup.key` (32 random bytes, root `0600`) and store a copy separately; install `/etc/nexolab/dr-backup.json`; `--plan` (reads nothing, writes nothing); one manual run in an approved window while recording Device Agent queue, `/health/ready` ingestion lag and container `RestartCount` before/during/after; `nexolab-dr-stream.py verify`; only then the timer (separate approval). _Take the first real backup after the object-metadata fix is installed (see section 8)._
2. **C — verified off-device copy** ([`dr-offdevice-copy-1631.md`](dr-offdevice-copy-1631.md)): format and `enroll` the media, `copy` the newest verified bundle **with the Pi's internet disconnected**, `verify-destination`, keep the custody receipt; run `nexolab-dr-readonly-health.py --offdevice-destination <media>`.
3. **B — independent isolated restore** ([`dr-isolated-restore-1632.md`](dr-isolated-restore-1632.md)): on the isolated host, no path to production, internet disconnected, restore **from the leaf-C media** in `mode=site`, record the receipt, RPO and RTO; record the read-only source observation right after the backup. Attach the receipt, its sidecar and the v2 inventory fields to #1632 / #1428.
4. Decide the **RPO** question: the tooling reports the gap between the objective (0 s) and a daily schedule honestly; accept it or change the objective.

Only when 1–3 are complete and recorded is gate G1 evaluable for closure.

## 6. Phase 2 — activation (OWNER-run; each step needs the owner's explicit approval)

**Option F — frontend-only first (no database change)** — the pattern used for #1522/#1638, available independently of Phase 1:

1. Verify both ZIP digests against GitHub and the extracted `frontend-runtime.tar.gz` SHA-256 values in section 1; check the 17 629 runtime file hashes in `frontend-runtime-files-sha256.txt`; confirm the public contract file says `status=PASS`.
2. Regenerate the guarded #1638 scripts with **only the release constants changed** (release id, source SHA `7db6e1a8…`, build IDs, artifact SHA-256 values, image tag, new HTTPS systemd drop-in name). Keep the previous LAN image and HTTPS release for rollback.
3. **LAN image: build from a tar-streamed context and compare every file with the artifact** (BuildKit context sync silently reused stale `.next` content in #1638). Never re-run a failed `execute`; follow the journal/rollback output.
4. Verify (section 7). Rollback: re-point to the retained previous image / HTTPS release.
5. Until the backend is updated, the saved-analysis-view _save_ shows an explicit error («Сервер не підтримує збереження вигляду аналізу.») instead of pretending to save; everything else works.

**Option B — full update through the version manager (after Phase 1):**

1. Verify the bundle archive SHA-256, extract, run `python3 scripts/verify-offline-bundle.py --source-repository eNgine9r/nexolab-platform <extracted dir>` (expects `"status": "verified"`).
2. `sudo python3 scripts/nexolab-version-manager.py stage --root /var/lib/nexolab/version-management --bundle <extracted dir>` — it re-verifies and records a host marker.
3. In **Settings → System Version** select the staged target, check that the plan shows source `7db6e1a8…`, schema `20260908_0037` → `20261122_0041`, enter the exact confirmation phrase (`APPLY <bundle-id>`). The worker validates the package, runs the capacity preflight, **creates and validates a PostgreSQL backup**, applies the package with pull disabled, migrates before readiness and verifies the database revision and Device Agent worker health.
4. Do not touch the Device Agent, MQTT or any RS-485 bus manually. Compare container IDs before/after: only telemetry-service, dashboard (and anything the bundle declares) may change.
5. This path replaces the frontends with the bundle's embedded builds; if Option F was done first, the build IDs change again — record them and re-run the parity check.

## 7. Post-activation verification (owner, authenticated browser + read-only checks)

- Identity API on every entrypoint reports source `7db6e1a8…` and the expected build ID (`scripts/check-frontend-entrypoint-parity.py` with the approved manifest mode for origin-specific builds); the OAuth gate still answers 302.
- `/health/ready` ready, ingestion lag small and **telemetry still advancing; no gap in acquisition during the window**; Device Agent `/health` 200 with the same container ID; database revision `20261122_0041`.
- Browser (LAN and signed-in HTTPS, 390 px and desktop): Overview, Live (device-grouped picker, 24 channels, presets and custom period, partial-history notice, alerts), Saved Dashboards (density, statistics, state lanes, events, **save view → reload → restore**, viewer cannot save), Energy, Refrigeration, exports (CSV, PNG, XLSX, print report), no client/API errors, **no extra acquisition requests** from chart interactions.
- Measure density timings on the Pi and record them labelled as Pi measurements.
- Record evidence in `.project/CURRENT_STATE.md`, `.project/LAST_CHECKPOINT.json` and the release issue. Print the operator signal only with this runtime proof **and** every gate in section 3 satisfied.

## 8. Rollback matrix

| Situation                                      | Action                                                                                                                                                                                                                                                                            |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Frontend problem (Option F)                    | Re-point LAN to the retained previous image and HTTPS to the previous release (guarded rollback). No data involved.                                                                                                                                                               |
| Backend update fails **before** the migration  | The worker leaves current evidence unchanged and data untouched; investigate from the operation evidence; no restore needed.                                                                                                                                                      |
| Backend update fails **after** the migration   | Do **not** downgrade the schema (downgrades refuse while operator data exists). The managed rollback to the previous package is refused by design; recover with the pre-update backup via the verified restore procedure (`disaster-recovery.md`, `dr-isolated-restore-1632.md`). |
| Application-only fault with a healthy database | An older telemetry image runs against the additive schema (nullable columns, new tables); this is an owner-reviewed manual image rollback, not the managed path.                                                                                                                  |

## 9. Known limitations and follow-ups

- Object-storage metadata (ETag, Content-Type) was **not** preserved by the first leaf-A snapshots (found in the isolated rehearsal); the fix is tracked in a dedicated pull request — take backups only after it is installed. Bundles taken before the fix restore the object bytes and checksums but not that metadata.
- The first release after 2026-11-30 or 2026-12-15 needs the security exceptions renewed or the findings gone (#1692).
- arm64 fidelity of the restore rehearsal is unverified (it ran on amd64); a spare Pi as the isolated host closes that.
- Not covered by software evidence: #1606, #1409/#1399, real-controller semantics, Embraco scale, Pi performance.

## 10. Boundaries

No Modbus or hardware write; no acquisition or polling change; no production migration, backup, restore, deployment or secret handling by an agent; no weakened security gate; no disaster-recovery gate bypassed.
