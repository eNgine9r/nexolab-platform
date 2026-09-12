# Issue #994 — 2026-09-12 consolidated HIGH container review

Date: 2026-09-12

## Fresh discovery evidence

Workflow-dispatch run `34699985764` scanned exact source `7864a95934c4ef471cfb82cbdcaeb259eca692c2` with `pull: true` and `no-cache: true` for every controlled image. Policy/inventory tests passed. Device Agent, Telegram Gateway and MQTT dynamic-security passed vulnerability policy. Telemetry Service failed closed only because four registered HIGH exceptions disappeared from the fresh Trivy report.

Removed stale Telemetry Service tuples:

- `gzip / CVE-2026-41992`;
- `libsqlite3-0 / CVE-2026-11822`;
- `libsqlite3-0 / CVE-2026-11824`;
- `libwebsockets19t64 / CVE-2026-78161`.

The discovery registry therefore moved from 95 to 91 exact HIGH entries. No Critical exception is permitted.

## Current reachability review

A current-source sweep found no runtime source path for tar extraction, HTML parsing, mount/umount/nsenter/unshare, cJSON/JSON Patch, gzip decompression of operator input, ACL mutation, or libwebsockets LECP CBOR. Exact FTS3/4/5 virtual-table and MATCH-query searches are negative. Device Agent and Telegram Gateway have no XML/pyexpat parser import or custom encoding callback. Telemetry Service uses `xml.sax.saxutils.escape` in PDF rendering, but the reviewed Expat exceptions are not for that image.

## Fix availability decisions

Fresh Trivy reports Device Agent/Telegram Gateway `CVE-2026-11940` with fixed Debian Python `3.13.5-2+deb13u5`, while current no-cache distroless Debian 13 still contains `3.13.5-2+deb13u4`. It likewise reports SQLite `CVE-2026-11822/11824` fixed in `3.46.1-7+deb13u2` while current distroless still contains `3.46.1-7+deb13u1`. These fixes are not yet consumed by the current upstream distroless base and require recheck rather than pretending the current image is fixed.

Debian Security Tracker still marks Trixie/security Expat `2.8.3-1~deb13u1` vulnerable for `CVE-2026-76956` and `CVE-2026-76957`; `2.8.4` is fixed in forky/sid. Existing JSON/Modbus/MQTT-only reachability boundaries remain unchanged for the two affected NEXOLAB images.

For `CVE-2026-78409`, Red Hat's current statement says the affected `X-mount.subdir` detached-tree path is util-linux `2.42` through `2.42.2` and explicitly states earlier v2.41 is not affected. Debian/Trivy still report the installed `2.41.5` package lineage, so exact exceptions remain only as a bounded scanner/vendor mapping disagreement; the NEXOLAB runtime also exposes no mount/fstab path.

## Late exact-head finding

After PR #998 restored the unrelated Telemetry Service MinIO CI fixture and `main` advanced, exact-head no-cache Container Supply Chain run `34702355254` at source `1e1576b9edc5eac5f3be017753c382fc39c19278` reported one new HIGH finding: `telemetry-service / libcjson1 / CVE-2026-87933`. Debian Trixie `1.7.18-3.1+deb13u1` is currently vulnerable with no fixed package. The defect is in `cJSONUtils_MergePatch*`. Debian Trixie package introspection confirms the vulnerable symbols are exported by `libcjson_utils.so.1.7.18`, while `mosquitto_ctrl` links `libcjson.so.1` but not `libcjson_utils.so.1` and has no cJSON Utils symbol reference. The NEXOLAB path remains the bounded authenticated `nexolab-dynsec-admin → mosquitto_ctrl dynsec` command contract, with no arbitrary JSON Merge Patch input. One exact short-lived exception is therefore added through `2026-09-15`, taking the candidate registry from 91 to 92 entries.

## Renewal boundary

All 92 retained exact HIGH exceptions are shortened to `2026-09-15`, owner `platform-security`. Remove earlier if a tuple disappears, the current distroless base consumes a fixed package, runtime reachability changes, authoritative affected-version guidance converges, or severity becomes Critical. The final candidate must pass a fresh exact-head no-cache Container Supply Chain run and NEXOLAB Merge Gate before merge.

No production deployment, service restart, Modbus/controller write, hardware write, secret operation, product-data deletion or named-volume deletion belongs to this review.
