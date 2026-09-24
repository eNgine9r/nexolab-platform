# ADR 0011: Local S3 object storage with VersityGW

- Status: Accepted
- Date: 2026-09-24
- Decision owners: Product Owner, NEXOLAB engineering
- Profile: `LOCAL_LAN`
- Work Package: Issue #1147

## Context

NEXOLAB requires private S3-compatible storage for equipment images and recovery artifacts while the
core runtime remains fully usable without internet, cloud accounts, paid services, license servers or
external telemetry. The prior MinIO Community runtime became unsuitable after its container supply
was withdrawn and the reconstructable legacy binaries failed current NEXOLAB vulnerability policy,
including CRITICAL findings that cannot be excepted.

A non-production evaluation of VersityGW `v1.8.0` verified the official amd64 and arm64 release
checksums, local POSIX storage, SigV4/path-style S3 operations, private-bucket behavior and a current
container scan with no HIGH or CRITICAL findings. The Product Owner approved VersityGW on
2026-09-24.

## Decision

Use **VersityGW v1.8.0** as the repository-owned local S3-compatible object-storage engine.

The runtime image is built from the exact official release archive for the target architecture and
must verify the committed SHA-256 before the binary enters the final scratch image. The supported
runtime architectures are `linux/amd64` and `linux/arm64`.

NEXOLAB continues to expose the existing application S3 contract: SigV4, path-style addressing,
private buckets, Put/Get/Delete, content type, custom metadata and presigned GET URLs. Bootstrap,
backup and restore use repository-owned boto3 tooling rather than the withdrawn MinIO `mc` client.

The Compose service keys `minio`, `minio-init`, `source-minio`, `restore-minio` and `minio-client`
remain temporarily as compatibility identifiers for existing automation. They do **not** authorize
new MinIO dependencies; new code and documentation use generic `object storage` terminology.

## Data and migration boundary

VersityGW POSIX data is stored in a new named volume ending in
`object-storage-versitygw-data`. The existing MinIO volume is not mounted into VersityGW and must not
be deleted or rewritten. Production deployment tooling fails closed when the legacy volume exists
without separately migration-proven VersityGW storage.

Actual production object migration and runtime cutover are separate Product Owner-gated operations.
The migration must use S3-level export/import, preserve object bytes and relevant metadata, verify
private access and content integrity, and retain the old MinIO volume/image as rollback authority
until post-cutover acceptance is complete.

## Offline and security requirements

- runtime network access is not required after the image/bundle is built;
- no mandatory cloud account, paid service, license server or CDN is permitted;
- amd64 and arm64 artifacts are checksum-pinned;
- the exact candidate must pass NEXOLAB container vulnerability policy with no unapproved HIGH or
  CRITICAL findings;
- the offline bundle carries the VersityGW image and repository S3 helper dependencies;
- object storage remains private and anonymous bucket listing must fail closed;
- production migration/cutover is never implicit in a normal source deployment.

## Consequences

The application-facing S3 API remains stable while MinIO-specific server/client dependencies are
removed. Recovery and browser acceptance remain backend-independent at the S3 boundary. A dedicated
migration/cutover Work Package is still required before the currently deployed MinIO production data
can move to VersityGW.
