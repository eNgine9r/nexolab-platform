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

The runtime image uses the exact official release archive when it passes current security policy,
or the reviewed same-release security rebuild defined below when that archive contains findings
with compatible toolchain/module fixes. Archive or source/SDK identity must be verified before
the binary enters the final scratch image. Supported runtime architectures remain
`linux/amd64` and `linux/arm64`.

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
- amd64 and arm64 release archives or source-build SDK inputs are checksum-pinned, and finished
  candidate images/artifacts are bound to immutable release-manifest digests;
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

## Security build amendment — Issue #1369, 2026-10-13

This engineering amendment becomes effective with the reviewed, GREEN merge of #1369 / PR #1370.
It preserves the Product Owner's approved engine, version, S3/POSIX behavior and separate
migration/cutover authority. It does not approve a runtime installation.

The official v1.8.0 archives now contain four HIGH Go/x-net findings with compatible fixes;
no fixed newer official VersityGW release was available during this review. An exception for
these fixed findings is prohibited. Build the same v1.8.0 source at immutable upstream commit
`fd04bc1df2656298577b82667a4195c77f8c7563`, which is the verified release tag target.
Never build a floating branch or silently substitute another product version.

The builder must:

1. verify the checked-out source commit;
2. SHA-256-verify Go 1.27.2 for its amd64/arm64 builder architecture against committed official
   SDK checksums and disable automatic toolchain selection;
3. apply the exact x/net v0.60.0 security module update and its required minimum-version graph
   (x/crypto v0.57.0, x/sync v0.23.0, x/sys v0.48.0, x/text v0.42.0), download modules through
   Go's checksum-verifying mechanism and run `go mod verify`;
4. compile the upstream release entry point `./cmd/versitygw` with CGO disabled and the original
   v1.8.0 release identity; check resulting Go/toolchain/module/architecture build metadata;
5. prove both supported cross-build targets, distinguish cross-build from native runtime proof,
   and admit the finished image only after current scans and S3/report/offline regression gates;
6. retain the source/SDK/module verification in the Dockerfile, SBOM and source/digest-bound
   image release evidence.

The final scratch image still contains only the gateway binary. SDK, Git, module downloads and
development internet access remain outside the installed offline runtime. A same-release source
rebuild must not silently include upstream feature changes or unreviewed dependency updates.

Rollback selects a previously validated, addressable image/package by its recorded immutable
digest, together with its original Dockerfile and source/binary supply recipe. It never rebuilds
the old version with today's toolchain and calls that the previous artifact. Do not replace or
delete the previous image, package, POSIX data volume or migration evidence. Before any guarded
update, recheck available backup/data protection and rollback compatibility with the retained
S3/POSIX data; restore through the approved owner-local procedure. A source merge does not
restore data, change a running container or authorize a site cutover.

If a fixed official archive becomes available, returning to the archive recipe requires a focused
review, committed architecture-specific checksums and the same fresh vulnerability/S3/offline
gates. Do not automatically replace this reviewed source recipe from a floating release tag.
