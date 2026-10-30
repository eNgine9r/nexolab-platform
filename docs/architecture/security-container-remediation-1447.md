# Security remediation #1447

This is a source-only proposal, not a production release or a vulnerability waiver.

## Verified baseline

Five GitHub Actions Trivy reports from run `41067085401` and source `e24d5bd30104709d4b06d899aed64b9fbee42196` report:

- `telemetry-service`: 73 HIGH, 5 CRITICAL.
- `object-storage`: 1 HIGH, 0 CRITICAL.
- `device-agent`: 0 HIGH, 0 CRITICAL.
- `telegram-gateway`: 0 HIGH, 0 CRITICAL.
- `mqtt-dynamic-security`: 0 HIGH, 0 CRITICAL.

These are x86_64 CI results, not deployed Raspberry Pi ARM64 evidence.

## Scoped remediations

- `Pillow==13.0.0` addresses the five CRITICAL Pillow findings and related HIGH findings.
- `msgpack==1.2.3` addresses `CVE-2026-114613` and updates the Dockerfile version assertion.
- Go 1.27.3 addresses Object Storage `stdlib/CVE-2026-111943`.

The official checksums are published at [Go downloads](https://go.dev/dl/):

- Linux amd64: `65efbc80fdc1fa2cd2631cad5b481777a68e8725f34e89f50fc6ac714e379b40`.
- Linux arm64: `a06e99309dbcbdca1a8ccd2282c3ee146e55930886e26b4f1193269587165f49`.

Go also publishes [reproducible build results](https://go.dev/rebuild).

## Remaining blockers

- The 48 existing HIGH vulnerability exceptions expired on 2026-10-20. They remain unchanged.
- Debian `libwebsockets19t64/CVE-2026-95114` has no reported Trivy fixed version in the baseline.
- Verify all current image/package/CVE tuples using a new exact-head five-image scan.
- Review each remaining HIGH tuple independently and record a bounded exception only with current evidence.
- Test Python application compatibility, offline operation, image provenance and ARM64 build behavior.

No security gate has been disabled. No Raspberry Pi service, production storage, credentials, network settings or hardware were modified.
