# Security Issue #1447 — 2026-10-30 controlled image remediation

**Scope of this source-only draft:** address new FIXED-VERSION vulnerabilities
found by `Container Supply Chain` while **retaining** all fail-closed guards,
isolated build identities and existing production volumes.

## Evidence baseline

From all five GitHub Actions Trivy JSON artifacts for
run `41067085401`, source
`e24d5bd30104709d4b06d899aed64b9fbee42196`
(x86_64 CI, **not** Raspberry Pi ARM64 or production):

| Image | HIGH | CRITICAL |
| --- | ---: | ---: |
| telemetry-service | 73 | 5 |
| object-storage | 1 | 0 |
| device-agent | 0 | 0 |
| telegram-gateway | 0 | 0 |
| mqtt-dynamic-security | 0 | 0 |

**Fixed versions provided by scanner:**
- `pillow` 5 CRITICAL and further HIGH → 13.0.0 (was constrained by
  `Pillow>=12.3,<13`).
- `msgpack` HIGH `CVE-2026-114613` → 1.2.3 (was pinned to 1.2.1,
  including Dockerfile runtime assertion).
- `object-storage` Go stdlib HIGH `CVE-2026-111943` →
  Go 1.26.10 or 1.27.3 (currently source `GO_VERSION=1.27.2`).
  **Not upgraded in this slice**: both official architecture-specific binary
  checksums, signed toolchain provenance, ARM64 compatibility and exact commit
  acceptance must first be independently validated.

A new Debian HIGH `libwebsockets19t64 / CVE-2026-95114` has no
Trivy FixedVersion. The existing exception registry has **48 entries all
expired on 2026-10-20**. They are NOT renewed by this PR. Existing policy
must continue rejecting the build until current high/critical tuples are
individually reconciled and every remaining exception justified with
source-bound scan evidence, a bounded expiry and an accountable owner.

## Safety / acceptance

- No production dependency install, Docker/site cutover, secrets, data edits,
  cloud dependency, Modbus write or hardware acceptance.
- The Pillow/msgpack changes are a proposed source-only security upgrade,
  not proof of library compatibility. Python smoke and full telemetry/service
  integration tests, image rebuild/Trivy and offline bundle need actual
  exact-head GREEN evidence.
- Never bypass vulnerability exception validation, redefine critical severity
  or claim green solely from a test fixture. Keep #1445 separate.
