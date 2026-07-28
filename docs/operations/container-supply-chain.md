# NEXOLAB container supply-chain release runbook

## Purpose

This runbook defines how NEXOLAB production images are inventoried, built, scanned, accepted, published, verified and rolled back.

The controlled images are declared in `security/container-images.json`:

- Device Agent;
- telemetry-service;
- Mosquitto Dynamic Security broker.

Pull-request validation is read-only. Only protected `main` and release-tag workflows may publish images or registry attestations.

## Security invariants

1. Every image is built from one exact Git commit.
2. The image contains immutable OCI source and revision labels.
3. Every image produces non-empty CycloneDX JSON and SPDX JSON SBOMs.
4. Every image produces a machine-readable Trivy JSON report.
5. Every Critical vulnerability blocks release. Critical exceptions are not supported.
6. Every High vulnerability must either be fixed or match one exact, non-expired image/package/CVE decision.
7. Wildcard packages, wildcard CVEs, duplicate decisions, expired decisions and stale decisions fail the Gate.
8. Release manifests bind the image digest, Dockerfile digest and all evidence digests.
9. Downloaded evidence is hashed again during aggregate verification.
10. Evidence must not contain credentials, private keys or runtime secret values.
11. Rollback uses an immutable registry digest, never an unverified mutable tag.

## Local policy validation

Run from the repository root:

```bash
python scripts/validate-container-supply-chain.py
python -m pytest -q \
  tests/test_container_supply_chain_policy.py \
  tests/test_container_vulnerability_policy.py \
  tests/test_container_release_manifest.py \
  tests/test_container_release_aggregate.py
```

The validator checks inventory paths, image names, target platforms and the vulnerability exception registry.

## Pull-request evidence Gate

The `Container Supply Chain` workflow performs the following for every image:

1. checks out the exact tested commit;
2. builds `linux/amd64` without publishing;
3. verifies the OCI revision and source labels;
4. captures the local image SHA-256 digest;
5. generates CycloneDX JSON;
6. generates SPDX JSON;
7. generates a Trivy JSON vulnerability report;
8. evaluates High and Critical policy;
9. generates a digest-bound image manifest;
10. scans evidence for secret-like material;
11. uploads per-image evidence;
12. downloads all image evidence into an aggregate job;
13. recalculates every Dockerfile and evidence digest;
14. produces one aggregate release manifest.

The workflow uses a full commit SHA for the Trivy action. Do not replace it with a moving branch or tag.

## Evidence layout

A successful aggregate artifact contains:

```text
evidence/
├── device-agent.cdx.json
├── device-agent.spdx.json
├── device-agent.trivy.json
├── device-agent.manifest.json
├── telemetry-service.cdx.json
├── telemetry-service.spdx.json
├── telemetry-service.trivy.json
├── telemetry-service.manifest.json
├── mqtt-dynamic-security.cdx.json
├── mqtt-dynamic-security.spdx.json
├── mqtt-dynamic-security.trivy.json
├── mqtt-dynamic-security.manifest.json
└── release-manifest.json
```

Each image manifest contains:

- repository;
- exact commit;
- generation timestamp;
- image ID and registry name;
- platform;
- image digest;
- Dockerfile path and digest;
- CycloneDX path and digest;
- SPDX path and digest;
- vulnerability-report path and digest.

## Vulnerability triage

### Critical

Critical findings always block release.

Required response:

1. identify the vulnerable package and reachable code path;
2. upgrade or remove the package;
3. reduce the runtime image if the package is unnecessary;
4. rebuild and rescan;
5. do not add a Critical exception.

### High with a fixed version

Upgrade to the fixed version and run the complete regression matrix. Do not create an exception for a High vulnerability when a compatible fixed package is available.

### High without a fixed stable package

A temporary decision is allowed only when all of the following are documented:

- exact image ID;
- exact binary package;
- exact CVE;
- concrete unreachable or mitigated runtime path;
- accountable owner;
- short expiry date.

Example structure:

```json
{
  "image_id": "device-agent",
  "package": "example-package",
  "vulnerability": "CVE-2026-00000",
  "reason": "The affected parser is not reachable from any Device Agent input path.",
  "owner": "platform-security",
  "expires_on": "2026-08-15"
}
```

The evaluator rejects a decision after its expiry date. It also rejects a decision that no longer matches a current High or Critical report entry. This forces resolved findings to be removed from the registry.

## Exception renewal

Renewal is not an automatic date extension.

Before renewal:

1. refresh the base image;
2. update application dependencies;
3. rerun Trivy with the current database;
4. check the upstream and Debian security trackers;
5. confirm that the vulnerable API remains unreachable;
6. review container privileges, mounts and exposed endpoints;
7. update the reason if the mitigation changed;
8. choose the shortest practical new expiry;
9. obtain a new code review.

Delete the decision immediately when the package is fixed or removed.

## Protected publication

On protected `main` and release-tag pushes, the workflow publishes all declared platforms to GHCR.

The published image includes:

- immutable Git SHA tag;
- applicable `main` or release tag;
- OCI source and revision labels;
- BuildKit SBOM attestation;
- maximum-mode provenance attestation;
- registry manifest digest.

Mutable tags are operator conveniences only. Deployment records must retain the immutable digest.

## Verification before deployment

Confirm that the release record references the expected repository and commit, then compare the recorded registry digest with the digest selected for deployment.

Recommended verification sequence:

```bash
gh run list --workflow "Container Supply Chain" --branch main
gh run view <run-id>
gh run download <run-id> --name container-release-evidence-<commit>
sha256sum evidence/*.json
```

For published images, inspect the registry digest and attestations with an OCI-capable verification client. The central-host deployment must reference:

```text
ghcr.io/engine9r/<image>@sha256:<digest>
```

Do not deploy only `:main`, `:edge` or another mutable tag.

## Secret leakage response

If evidence scanning detects a private key, credential or secret-like value:

1. block the release;
2. do not upload or redistribute the artifact;
3. rotate the exposed credential immediately;
4. identify whether the value came from an environment variable, image layer, process argument, log or generated report;
5. remove the source and rebuild from a clean commit;
6. verify Git history and workflow artifacts;
7. record the incident in the security audit trail.

## Rollback

Rollback never rebuilds an old tag.

1. select the last accepted release manifest;
2. verify its repository, commit and evidence digests;
3. deploy the exact previous registry digest;
4. keep PostgreSQL, SQLite and Mosquitto persistent volumes intact;
5. verify health, migrations and broker compatibility;
6. record the rollback reason and selected digest;
7. keep the failed release blocked until remediation is merged.

Do not:

- disable the vulnerability Gate;
- extend an exception without review;
- allow Critical vulnerabilities;
- remove hostname or certificate verification;
- expose plaintext MQTT;
- delete persistent volumes as a rollback shortcut.

## Deferred operational Gate

The following remain dependent on actual central-host and registry policy access:

- GHCR retention and immutability policy;
- production deployment by digest;
- external attestation verification;
- registry access review;
- long-term evidence retention;
- rollback rehearsal on the central host.
