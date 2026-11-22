# NEXOLAB #1441 — offline read-only backup health

**Source-only. No backup capture, service installation or site activation.**

This command detects missing recovery evidence and a missing or disabled application backup timer.

## Usage

```bash
python3 scripts/nexolab-dr-readonly-health.py
python3 scripts/nexolab-dr-readonly-health.py --inventory /path/to/sanitized-v2.json
```

Optional evidence inputs (all read-only):

```bash
# #1631: re-read the newest bundle on the mounted off-device media against its custody receipt
python3 -I -B scripts/nexolab-dr-readonly-health.py --offdevice-destination /mnt/nexolab-dr/nexolab
# #1632: consume a site-mode isolated restore receipt (+ the custody receipt of the restored bundle)
python3 -I -B scripts/nexolab-dr-readonly-health.py \
  --restore-receipt /path/evidence-1/nexolab-dr-isolated-restore-receipt.json \
  --custody-receipt /mnt/nexolab-dr/nexolab/nexolab-dr-YYYYMMDDTHHMMSSZ-xxxxxx.custody-receipt.json \
  [--offdevice-destination /mnt/nexolab-dr/nexolab] [--restore-receipt-max-age-days 35]
```

The optional inventory input is a non-symlink JSON file, mode 0600, at most 512 KiB.
No credentials or private telemetry are permitted.
The existing offline #1433 eight-store contract validates the supplied receipt.

Only the fixed `nexolab-dr-backup.timer` is queried using read-only `systemctl show`.
The probe also checks root filesystem free space. It does not change anything.

## States and checks

The report uses `BLOCKED`, `UNVERIFIED` and `REPORTED_OK` for individual gates.
Its overall status is always `BLOCKED`, with exit code 78 and no site authorization.

- Missing, inactive, disabled or nonpersistent application backup timer.
- Missing, incomplete, duplicate, invalid, stale or future-dated eight-store receipt.
- Less than 20 GiB free on the root filesystem.
- Unverified independent encrypted off-device copy or actual isolated restore (see below for the receipt rules).
- Missing real equipment acceptance.

## Isolated restore gate (#1632)

Without `--restore-receipt`/`--custody-receipt` the `isolated_restore` gate is `UNVERIFIED`, exactly as before.
With them, the gate is `REPORTED_OK` only if **every** rule below holds; otherwise it is `BLOCKED` with the
first failing rule as the reason (a claim alone never changes the gate). This change was explicitly requested by
the Product Owner.

| Input                                                                                                                                                                                          | `isolated_restore`                             |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| no restore option                                                                                                                                                                              | `UNVERIFIED` (unchanged)                       |
| `--restore-receipt` without `--custody-receipt` (or the reverse)                                                                                                                               | `BLOCKED`                                      |
| receipt missing, symlink, over 8 MiB, not UTF-8 JSON, duplicate keys, wrong kind/schema/issue, missing typed fields                                                                            | `BLOCKED`                                      |
| `.sha256` sidecar missing, malformed, naming another file, or not matching the exact receipt bytes                                                                                             | `BLOCKED`                                      |
| run recorded `error`/`refused`; `status` not `PASS`; status inconsistent with the checks                                                                                                       | `BLOCKED`                                      |
| rehearsal receipt (`evidence_class` not `SITE_ISOLATED_RESTORE`, statement not the site statement), any waiver                                                                                 | `BLOCKED`                                      |
| any `isolation.*` check not PASS; target not recorded isolated/offline; stack egress not blocked                                                                                               | `BLOCKED`                                      |
| any mandatory check (`REQUIRED_CHECKS` + `isolation.internet_disconnected`, `source_observation.consistent`, `dashboards.same_series_as_source`) missing, or any check in the receipt not PASS | `BLOCKED`                                      |
| `object_storage_s3.metadata_fidelity` not `PRESERVED` (e.g. `DEGRADED`), ETag/Content-Type mismatches or missing ETags                                                                         | `BLOCKED`                                      |
| any receipt warning (emulated architecture, bundle on the restore host's own filesystem, anything else)                                                                                        | `BLOCKED` (strict default; no override exists) |
| custody receipt invalid/non-canonical, or `inputs.custody_receipt_sha256` ≠ its bytes, or bundle name/size/SHA-256, destination kind/identity or `copied_at` differ                            | `BLOCKED`                                      |
| `restore_target_identity_sha256` = `destination_identity_sha256`                                                                                                                               | `BLOCKED`                                      |
| with `--offdevice-destination`: destination does not re-verify, or its newest bundle is not the restored bundle                                                                                | `BLOCKED`                                      |
| a store missing/not `verified`/not `new_target`/not `source_untouched`, or `verification_sha256` does not recompute                                                                            | `BLOCKED`                                      |
| timestamps out of order, `completed_at` more than 1 min in the future, or older than the maximum age (default 35 days)                                                                         | `BLOCKED`                                      |
| `rpo_seconds`/`rto_seconds` missing, negative, or inconsistent with the receipt timestamps                                                                                                     | `BLOCKED`                                      |
| all of the above hold                                                                                                                                                                          | `REPORTED_OK`                                  |

**RPO/RTO objectives warn, they do not block.** The gaps are recomputed against the current
`security/disaster-recovery-assets.json` objectives and echoed in `isolated_restore_receipt.rpo_rto` and
`isolated_restore_receipt.findings` (e.g. "RPO objective missed by … s"). The software RPO objective (0 s) describes
the quiesced CI drill, so a daily backup always misses it; blocking on it would make the gate unreachable without
adding information. The owner must accept the gap or change the objective. A missed objective is never hidden.

"Started from the off-device copy" is established by the custody binding (the restored bytes are the bundle the
custody receipt describes, and that receipt requires an independent destination) plus the restore tool's site-mode
refusal to restore a bundle from the restore host's own filesystem (in a rehearsal that is only a warning, which
this gate rejects). The bundle path itself is not recorded in the receipt.

**What `REPORTED_OK` means, and what it does not.** It is _receipt-attested and re-verified locally_: the receipt is
intact (sidecar), structurally valid, strict site-mode evidence with every check PASS, bound to the custody receipt
(and, if given, to the newest copy re-read on the media), recent, and internally consistent. It is **not** an
independent proof that the physical restore happened as described (isolation, unplugged uplink and the restore host
are attested by the receipt and the owner's record of the setup), and it is **not** production or site readiness:
the overall status stays `BLOCKED`, exit code 78, `site_activation: NOT_AUTHORIZED`.

An enabled timer is not evidence that its backup job succeeded.
A recent v2 receipt is an attestation, not independent proof of actual contents.
A PostgreSQL archive list cannot prove complete eight-store recovery.

## Operational boundary

#1428 remains open: the site has only a reported partial PostgreSQL snapshot.
There is no independently verified complete encrypted backup or isolated restore.
The old microSD partition is not an approved backup destination.

Do not activate a schedule, access secret keys, alter Docker or perform Modbus writes.
#1399 site recovery needs separate Product Owner approval and full restore evidence.
A GREEN source-only PR is not a Raspberry update authorization.
