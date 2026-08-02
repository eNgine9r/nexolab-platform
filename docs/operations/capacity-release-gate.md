# NEXOLAB release-candidate capacity Gate

## Purpose

This Gate is a deterministic **software regression boundary**, not a production-host capacity certificate. It proves correctness, boundedness and no-loss behavior for the central MQTT → Telemetry Service → PostgreSQL path on an isolated GitHub Actions runner.

It does not require Raspberry Pi, RS-485 devices, Tailscale, the laboratory network or the actual central host.

## Versioned workload

The canonical policy is `infrastructure/performance/release-workload.v1.yaml`.

| Phase          | Contract                                                                                     |
| -------------- | -------------------------------------------------------------------------------------------- |
| Topology       | 6 simulated nodes, 8 streams each, 48 total streams                                          |
| Steady state   | 48 events/s for 60 s; exactly 2,880 persisted events                                         |
| Steady latency | capture-to-persistence p95 ≤ 3 s                                                             |
| Queue          | maximum utilization < 70% during steady traffic                                              |
| Replay         | 5,000 valid events; drain ≤ 120 s                                                            |
| Idempotency    | replay all 5,000 event IDs again; zero new rows                                              |
| REST           | bounded concurrent latest/history queries with p95 limits of 1 s / 2 s                       |
| WebSocket      | 20 conforming clients; 96 expected events per client; zero loss                              |
| Recovery       | stop PostgreSQL, retain 240 accepted events, restart and drain while 48 live events continue |

Policy changes must remain explicit and reviewed. The validator rejects unknown fields, inconsistent event counts, weakened latency bounds, incomplete duplicate replay and unbounded runtime/evidence settings.

## Isolation and safety

The capacity Compose overlay gives PostgreSQL, Mosquitto and MinIO unique volume names derived from `COMPOSE_PROJECT_NAME`. All published ports bind to loopback. Runtime credentials are generated per CI run, masked and scanned out of uploaded evidence.

The Gate uses fresh volumes and fails if telemetry already exists before the workload starts.

## Evidence

A successful run generates `test-results-capacity/` with:

- exact PostgreSQL counts and uniqueness checks;
- steady/replay latency and queue samples;
- REST p50/p95/p99 measurements;
- per-client WebSocket delivery results;
- controlled PostgreSQL outage and recovery evidence;
- before/after telemetry metrics;
- container resource observations;
- sanitized Compose status and logs;
- `release-readiness-manifest.json` binding the commit, policy digest, component identities and SHA-256 digest of every artifact.

`verify_capacity_evidence.py` rejects missing, modified, duplicate, absolute, backslash-based or path-traversing artifacts.

## Local execution

Requirements: Docker with Compose v2, Python 3.13, `pyyaml` and `websockets`.

```bash
python -m pip install pyyaml websockets
bash scripts/run-capacity-acceptance.sh
```

On success, the script verifies the evidence and removes the isolated containers and volumes. Set `KEEP_CAPACITY_STACK=1` only for controlled local diagnosis; never use it in shared CI.

## Failure interpretation

- **Count/uniqueness failure:** persistence or workload identity regression; release blocked.
- **Queue drop/dead letter:** valid traffic was lost or rejected; release blocked.
- **Latency-only failure on hosted CI:** inspect resource observations and repeat only after confirming no correctness failure. Threshold changes require reviewed policy updates, never an ad-hoc retry loop.
- **WebSocket missing event:** live fan-out contract regression; release blocked.
- **Recovery failure:** accepted work did not drain, readiness did not recover, or retry behavior became uncontrolled; release blocked.
- **Manifest failure:** evidence is incomplete or not trustworthy; release blocked.

## Deferred actual-host Gate

The following remain explicitly deferred until central-host access exists: production sizing, multi-hour soak, real NVMe/disk IOPS, Ethernet loss, kernel/network tuning, long-term Prometheus storage, final operator concurrency and physical Raspberry Pi backlog replay.
