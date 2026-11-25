# Acceptance programme — network independence and recovery (#1734, #1735, #1399, #1397)

Run after WP2c phase 4, with the owner on site, each scenario separately approved. **Pass** requires the runtime evidence listed; a successful script or CI run alone is never a pass. No Modbus writes; hardware stays read-only.

## Common evidence (collected by `nexolab-network-compat-recovery.py verify --share-evidence`)

- readiness `ready`, `ingestion_lag_seconds`, `last_persisted_at`;
- PostgreSQL max id before and after (growth), and 10-minute `captured_at` buckets (no gap, no wrong timestamps);
- Edge broker `$SYS`: `publish/messages/sent` growth, `store/messages/count`, `publish/messages/dropped` delta = 0;
- LAN UI through the gateway from a second device, HTTPS through Tailscale, `lab.nexolab`;
- Device Agent `/health` `clock.synchronized` (after WP2e), `queue_depth`;
- container restart counts and network endpoints.

## Scenarios

| #   | Scenario                     | Procedure                                                      | Pass criteria (in addition to the common evidence)                                                                                                 |
| --- | ---------------------------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| A1  | Ethernet only                | Wi-Fi off, cable in                                            | LAN UI via `http://<eth0>/` from a client; no dependency on 172.18.48.66                                                                           |
| A2  | Wi-Fi only                   | cable out, `LAB KK1` (after #1735)                             | UI via `http://<wlan0>/`; DHCP lease, route, DNS valid; Tailscale reconnects                                                                       |
| A3  | Ethernet ↔ Wi-Fi switching   | unplug/replug cable while sampling                             | no ingestion gap > 30 s; dropped delta 0; UI reachable on the new address                                                                          |
| A4  | DHCP address change          | change the reservation or renew to a new address               | no backend restart needed; UI on the new address; Edge bridge unaffected (Docker DNS)                                                              |
| A5  | No internet                  | block the upstream route (LAN stays)                           | local monitoring, charts and ingestion continue; Tailscale reports offline; clock stays synchronised (RTC/local NTP)                               |
| A6  | Reboot                       | `systemctl reboot` (approved window)                           | all containers healthy with endpoints within 5 min with no manual step (`boot-repair` log shows OK or repair); correct time before first sample    |
| A7  | Power loss, offline boot     | power off ≥ 10 min with the network disconnected, boot offline | `date -u` within seconds of a reference before sampling; `captured_at` monotonic                                                                   |
| A8  | Central unavailable for long | stop the Telemetry Service for 2 h (approved), then start it   | after #1397/#1445/#1451: no Edge row deleted before the PostgreSQL receipt; all rows arrive; dropped 0. Before them: record measured loss honestly |
| A9  | Docker daemon restart        | `systemctl restart docker` (approved)                          | endpoints and ports restored automatically; no data loss beyond the queue                                                                          |
| A10 | Tailscale with internet      | after A1–A4                                                    | HTTPS UI and OAuth gate (302) work; `lab.nexolab` unchanged                                                                                        |

## Report

For each scenario: date, approver, start/stop times, evidence files, pass/fail, and the measured gap and lost rows (never assumed zero).
