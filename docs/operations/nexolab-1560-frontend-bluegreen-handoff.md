# NEXOLAB #1560 — HTTPS frontend-only blue/green handoff

**Status (2026-11-10): first operator execution failed closed, root rollback verified, old Nginx restored; new isolated service remains running and is ready for a guarded promotion. Production HTTPS has NOT switched.**

## Outcome and boundary

Product Owner requested the new UI on the running NEXOLAB. Exact release `08f1c8a4ed9212c25697d338583845bed5218ee5` was built off-device by successful [GitHub ARM64 workflow 42805566839](https://github.com/eNgine9r/nexolab-platform/actions/runs/42805566839), and the **matching LAN and protected HTTPS** artifacts were SHA-256 validated and downloaded into an isolated Raspberry Pi staging directory.

This runbook updates **only the protected HTTPS Next.js frontend**. The LAN Docker dashboard, central/edge services, database, object store, MQTT, RS-485 and Docker/IPAM are not recreated, restarted or altered. The already-running HTTPS frontend on `127.0.0.1:3100` remains active. Candidate uses `127.0.0.1:3104` with the _same compiled HTTPS/public auth/organization contract_, separately packaged in `/opt/nexolab-external/releases/1560-08f1c8a4...`.

Existing Nginx OAuth `auth_request` guards are retained. The only allowed gateway change is two protected Next.js proxy targets, now routed to an upstream with **candidate primary / original automatic backup**. Nginx is syntax-checked before a graceful HUP reload, without a Docker restart or deleting old assets. Rollback restores the original Nginx config byte-for-byte and sends HUP.

## Known blockers and explicit risk

- **#1428:** No independently proven encrypted complete off-device backup or isolated restore of PostgreSQL, objects, MQTT/DynSec, edge SQLite and local-auth keys. This frontend-only procedure does not create one and **cannot be presented as full site DR acceptance**.
- **#1409:** Active Docker bridge `172.18.0.0/16` overlaps physical `172.18.48.0/21`; this procedure must **not** change or restart Docker/IPAM.
- The current protected frontend has **nine source-specific systemd drop-ins**. Never edit/delete/replace those drop-ins for #1560.
- The remote assistant's service connection disallows root/sudo commands. Site activation therefore needs a **single operator-run privileged command** on the Raspberry Pi. Do not attempt to bypass remote connector permissions.
- Source CI and isolated visual fixtures do **not** prove production user login/permission acceptance. Operator browser acceptance is required after any actual handoff.

This narrowly scoped UI-only handoff is offered for separately approved operator execution; the systemic #1428/#1409 blockers remain open and must be resolved before any full-stack release. Preserve the root rescue journal, old running service and backups.

## Preflight (unprivileged, actually executed)

```bash
cd /home/nexolab/commander-workspaces/nexolab-1560-bluegreen-release-20261110
python3 scripts/nexolab-1560-bluegreen-handoff.py check
```

Checks pinned main SHA, ARM64 artifact checksums, all 19,004 extracted runtime-file hashes, identity/build ID, exact existing production HTTPS contract, prior runtime source, old frontend HTTP, Telemetry readiness, Device Agent health and protected Nginx topology. The output includes the current SHA256 of Nginx config: **it must be reviewed again immediately before execution**.

## Failed first attempt — root cause and verified recovery (2026-11-10)

The Product Owner executed `execute` with the observed exact Nginx config SHA. The script reported `New loopback frontend did not become healthy` and `EXTERNAL_NGINX_ROLLBACK_VERIFIED`; no protected proxy change persisted. Read-only direct inspection confirmed that the **new** isolated `nexolab-external-ui-1560.service` was in fact healthy on port `3104` with HTTP 200, but `/api/runtime-identity` returned `source_commit: null`. The packaging helper had set `identity_source=verified_offdevice_arm64_release_1560`, which the existing identity reader **rejects**. Both the staging and installed manifest were corrected to its supported `offline_image_manifest` provenance with exact source/build ID preserved. After correction, the running `3104` identity API returned source `08f1c8a4ed9212c25697d338583845bed5218ee5`, build `MCPKmYsrQCxN9zwMwDDnV`, identity source `offline_image_manifest`. **No service restart or hardware/DB change** was required.

The failed attempt left a root-protected rescue journal, the installed new service, and the original running `3100` service. **Never rerun `execute` after this incident:** it intentionally fails closed when those resources exist. The new script has a separate, state-aware `promote` path that compares the original and saved candidate Nginx configs byte-for-byte, validates the root journal, verifies both running frontend identities and the existing hardened unit, and only then applies the Nginx proxy switch with automatic rollback on failure.

## Resume existing protected handoff — NOT YET RUN

Before attempting a new root action, require required exact-head GitHub CI GREEN, physical/console rollback access, and owner acceptance that #1428 full independent off-device DR proof is still unavailable. Verify the preflight again:

```bash
cd /home/nexolab/commander-workspaces/nexolab-1560-bluegreen-release-20261110
python3 scripts/nexolab-1560-bluegreen-handoff.py check
```

Confirm the reported Nginx SHA still matches the reviewed value. Then, **only for the already-installed and verified dual-service state**, run:

```bash
sudo /usr/bin/python3 -I -B scripts/nexolab-1560-bluegreen-handoff.py promote \
  --expected-nginx-sha256 b76c1120ae9e0981a8f1ba49caf9c6091d754df4b2649cf32cc36650d4e97f02 \
  --approved-frontend-only
```

Expected indicator after success: `EXTERNAL_BLUEGREEN_PROMOTED 08f1c8a4...` plus warning that full site DR and authenticated operator browsing remain unverified. On failure, do **not** delete root journal, edit Nginx manually, clear service state or try `execute` again; preserve output and inspect actual service status. The script restores the original Nginx automatically if a change fails.

## Recovery/rollback (operator only)

```bash
sudo /usr/bin/python3 -I -B \
  /home/nexolab/commander-workspaces/nexolab-1560-bluegreen-release-20261110/scripts/nexolab-1560-bluegreen-handoff.py rollback
```

The rollback compares current Nginx bytes against its protected original and the exact installed candidate; any independently modified config fails closed. No database rollback, image restoration or Modbus write occurs. Do not delete old systemd drop-ins, old frontend release, candidate release, root rescue journal or application data.

## Acceptance evidence required AFTER actual activation

1. Old `127.0.0.1:3100` stays 200; new `127.0.0.1:3104/api/runtime-identity` reports exact target source and build; gateway nginx remains active and anonymous OAuth access still denied.
2. Authenticated human browser: protected HTTPS login, Overview, Sessions, Reports, role-filtered menu, back/forward, 390px and desktop layouts. Check for 404, blank dashboard or repeated redirects.
3. Real Telemetry Service `/health/ready` and Device Agent `/health` both remain 200; real data freshness/sensor acquisition verified without write; inspect systemd/NGINX errors.
4. Optional rollback drill only with explicit owner instruction and live session monitoring; show exact source/build before/after and absence of telemetry interruptions.
5. Record exact runtime evidence in `.project/CURRENT_STATE.md`, `.project/LAST_CHECKPOINT.json`, linked Issue #1560. Do not say 🟢 «Оновлюйся» or mark site GREEN without this runtime proof.

## Developer verification already run

Source-only preview via real ARM64 Next.js candidate at a temporary loopback port: `/login`, `/sessions`, `/reports` HTTP 200; browser preview for Sessions/Reports used explicitly labeled test fixtures and therefore is **not** live hardware/role acceptance. Generated Nginx blue/green config passed Nginx `-t` with redirected temporary pid/cache directories. Eight focused handoff/resume contract tests passed, including altered journal/config rejection. The first operator execution rolled back before protected proxy activation; new service is healthy and identity-corrected, but active HTTPS Nginx still uses the old UI.
