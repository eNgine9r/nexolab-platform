# NEXOLAB Raspberry Pi deployment evidence — Issue #1307

- Date/time: 2026-10-08 12:35:44 EEST (post-check through ~12:38).
- Site: `nexolab-edge-01`, `LOCAL_LAN`, Raspberry Pi, runtime mode `lan`.
- Authorization: Product Owner expressly requested current-main Raspberry update and executed reviewed command in Raspberry terminal.
- Previous source: `75d9c75f8d1901d6b639ec711bf3784e22ed0642`. Target source: `d00a83bfc83fb120777c721b5e46fa50ae455c7d`.
- GitHub main push CI run: `37748119964` GREEN. Native ARM64 artifact build run: `37751399612` GREEN. Frontend SHA256 manifest checked OK.
- Frontend build ID: `hA8usmV6ZKwgZUYhmOLHZ` (active identity verified read-only).
- Deployment evidence: `runtime/deployments/20261008T092219Z`, script printed `DEPLOYMENT PASSED`.
- Pre-upgrade evidence present and nonempty: `postgresql-pre-upgrade.dump` (767538771 bytes), `edge-sqlite-pre-cutover.db` (290816 bytes), `runtime-evidence.tar.gz` (2539446366 bytes), `capacity-preflight.txt` (834 bytes).
- Prior rollback frontend release preserved: `runtime/frontend-releases/75d9c75f8d1901d6b639ec711bf3784e22ed0642-20261007T061059Z`.
- Device Agent container image: `sha256:514b504bad13e8cf4d7776a4e0670fb187d8149aa8ca75d6abc6b814ad2da323`; pre-cutover image preserved as `sha256:5344b4bef506d89923afd39413ee1bd7d1bb668ac1d123ed899a6d22fa58b957`.
- Site readiness: Dashboard, telemetry/API, Device Agent, Prometheus, Alertmanager, Grafana and storage all HTTP 200. Core Docker containers running.
- Live acquisition: initial transient degraded status (one RS485-main protocol error) cleared autonomously. Later Device Agent health `ok`, 3/3 bus workers healthy, zero degraded/cooldown endpoints, MQTT connected, queue zero, samples increased 149 → 237 → 325.
- Safety: No Modbus/controller/hardware writes or data-volume deletion. Core online services use local LAN; no required cloud runtime dependency added.
- Not claimed: physical hardware protocol acceptance, long-duration offline disconnected operation, restore drill of the newly created backup, fully authenticated operator Wave 2 (#1300).
- Warnings for follow-up: `du` reported historical Telegram evidence folders unreadable during preflight (capacity nonetheless PASS); Compose reported orphan Telegram gateway container, which was deliberately not deleted. No forced cleanup.

This report records bounded actual-host execution evidence, not fabricated hardware or disaster-recovery acceptance.
