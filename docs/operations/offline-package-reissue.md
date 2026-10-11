# Reissue packages for retained migrated storage

An offline package may contain the same VersityGW version but a different image
from the retained migration authority. Such a package cannot replace this site's
storage. Do not change the authority, retag a rebuilt image as accepted, repeat
object migration, restore databases or overwrite the original package.

Before preparing a protected frontend, the version worker runs the installed,
reviewed host verifier's read-only site-storage preflight against the package.
This preserves rollback to immutable older packages whose own verifier predates
the new preflight flags. Deploy the host verifier and archive module alongside
the worker; do not rewrite an old package to add those flags.
The direct installer runs the same check before
loading images. The existing migration proof still validates source ancestry,
exact native image identity, active storage and retained volume identities.

Image verification derives config, OCI manifest/index and layer digests from the
immutable archive. Docker's classic config ID and containerd's descriptor ID are
accepted only when this digest chain proves the same platform and root filesystem.
Tags, version labels, entrypoints and equal filesystem layers alone are insufficient.
The installer captures verifier output in a checked assignment before evaluating
exports, so a failed image check cannot continue using inherited image variables.

With explicit owner release-scope approval, export the exact retained storage
image using `docker image save`, then generate new CycloneDX and SPDX SBOMs against
that export. Use the existing pinned scanner in an isolated container with no
network, no production volume or serial-device mounts and bounded resources.
Preserve the export checksum, scanner identity, SBOM checksums and prior packages.

Run `scripts/reissue-offline-bundle.py --help` from the reviewed clean tooling
checkout. It requires the original manifest checksum, accepted storage export
checksum/runtime digest, new SBOM directory, reviewed tooling commit, distinct
version and new output directory. It copies existing application-image bytes and
protected frontend assets; it performs no builds, Docker imports, tag changes or
production activation. It preserves the accepted storage OCI index and its
provenance, removes the replaced storage graph, regenerates digest-bound manifests
and checksums, and verifies the new package. Existing archives remain immutable.
The update orchestrator uses the digest-bound original bundle ID and manifest
checksum in reissue provenance to prefer the compatible reissue when both are in
the catalog. Install the reviewed host orchestrator alongside the worker; package
installation does not replace these host maintenance tools automatically.

Archive/file checks are preparation evidence. Stage the distinct packages, prove
native loaded-image identities and full hardware installer preflight, and only
then perform an explicitly approved canonical owner handoff. Candidate or source
deployment evidence does not establish packaged authority. Actual LAN/HTTPS update
and rollback, telemetry progress and worker filesystem permissions require their
own runtime evidence.
