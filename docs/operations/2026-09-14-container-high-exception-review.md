# 2026-09-14 HIGH container exception review

Issue: #1012. Discovery candidate: `02f42ff68c6189bc4c0cf2fcfa4be0503b0667bf`.
Fresh no-cache Container Supply Chain run: `34826380930`.

## Result

The initial 92-entry registry failed closed because 12 Device Agent / Telegram Gateway Python and SQLite tuples had disappeared from fresh images. Those 12 stale exceptions were removed. A second exact-head no-cache run passed for every controlled image with 80 HIGH findings, zero CRITICAL findings, and a 1:1 match between fresh HIGH tuples and the corrected 80-entry registry.

The retained exceptions are bounded through **2026-09-21** only. They must be removed sooner if a tuple disappears, a compatible fix becomes consumable, current reachability changes, or severity becomes Critical.

## Current reachability and version evidence

No service runtime source changed between the 2026-09-12 review source and the #1012 discovery candidate; the only change under the broader runtime/infra paths was the browser-acceptance MinIO registry overlay. Current source sweep found no XML/pyexpat/XMLParser/UnknownEncodingHandler, HTMLParser, infocmp/terminfo, ACL mutation, cJSONUtils/MergePatch/ApplyPatches, systemd-homed/polkit, nsenter/unshare, X-mount, or application `/etc/fstab` path.

Fresh installed versions include Python `3.13.5-2+deb13u5`, Expat `2.8.3-1~deb13u1`, util-linux `2.41.5-0+deb13u1`, cJSON `1.7.18-3.1+deb13u1`, systemd libraries `257.13-1~deb13u1`, and ncurses `6.5+20250216-2`. Trivy reports no fixed version for the retained HIGH findings in this exact image set.

## Mandatory special rechecks

- `CVE-2026-78409`: Red Hat CNA states the X-mount.subdir fast path affects util-linux 2.42 through 2.42.2 and explicitly excludes v2.41, while Debian Security Tracker still marks Trixie 2.41.5 vulnerable/no-DSA. The exact scanner exception is retained because authoritative sources disagree, and the NEXOLAB runtime has no reachable user-fstab/X-mount application path.
- `CVE-2026-76956` / `CVE-2026-76957`: Debian still marks Trixie/security Expat 2.8.3 vulnerable; 2.8.4 is available in forky/sid, not the current Trixie contract. Device Agent and Telegram Gateway expose no XML/pyexpat/custom-encoding parser path.
- `CVE-2026-87933`: Debian still marks Trixie cJSON 1.7.18 vulnerable with no fixed package. Current source contains no cJSON Utils MergePatch/ApplyPatches path, and no service runtime source changed since the prior `mosquitto_ctrl` binary-linkage proof.

External references reviewed: Debian Security Tracker entries for CVE-2026-76956, CVE-2026-76957, CVE-2026-87933 and util-linux; Red Hat CNA entry for CVE-2026-78409 and its upstream advisory reference.

Production deployment, runtime containers, persistent data, Modbus, and hardware were not changed by this review.
