# #1428 disaster recovery: minimal owner checklist

One page for the Product Owner: what to have, in which order, what each step proves, and what the agent does. Detailed commands live in the linked runbooks. #1428 is **done only when phase D passes**. A backup that has never been restored elsewhere is not recovery evidence.

## What to have ready (physical)

| Item                                                       | Purpose                                    | Rule                                                                                 |
| ---------------------------------------------------------- | ------------------------------------------ | ------------------------------------------------------------------------------------ |
| **A. Backup SSD** (new, dedicated, ≥ 64 GB)                | Off-device bundle copies (#1631)           | Never holds the key                                                                  |
| **B. Key stick** (small USB, key only) or **paper escrow** | Second custodian of the encryption key     | Kept at a different place from the Pi and from SSD A                                 |
| **C. Isolated restore host**                               | Independent restore (#1632)                | A spare Raspberry Pi (arm64) is preferred; it must be fully offline during the proof |
| **Custody register** (paper or document)                   | Fingerprints, dates, custodians, locations | No key material, ever                                                                |

## Order and gates

| Phase                               | Who                                                                                            | What                                                                                                                                                                             | Proves                                                                                            | Runbook                                                                            |
| ----------------------------------- | ---------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| **A. Activate**                     | Owner (sudo)                                                                                   | Install the pinned DR-A package, render the site config, create the key, `--plan`, install the unit (not the timer)                                                              | Config valid for all 8 stores; capacity OK                                                        | [`dr-site-activation-1428.md`](dr-site-activation-1428.md) steps 1–5               |
| **A2. First backup**                | Owner approves `backup.start`; agent runs it through the broker and records disruption metrics | One encrypted bundle plus receipt (`CAPTURED_RESTORE_UNVERIFIED`)                                                                                                                | Capture works without stopping services                                                           | steps 6–7                                                                          |
| **B. Key custody**                  | Owner only                                                                                     | Copy the key to the key stick (or paper); record **both** fingerprints in the register (below)                                                                                   | The key survives loss of the Pi                                                                   | [`dr-offdevice-copy-1631.md`](dr-offdevice-copy-1631.md) "Key custody procedure"   |
| **C. Off-device copy**              | Owner (sudo)                                                                                   | Enroll SSD A once, copy the newest verified bundle with `nexolab-dr-offdevice-copy.py` from the same pinned package, `verify-destination`, unmount, store SSD A away from the Pi | The bundle survives loss of the Pi; custody receipt                                               | same runbook, "Offline-capable copy procedure"                                     |
| **D. Independent restore**          | Owner, on host C, offline                                                                      | Restore from SSD A with the key from B; `preflight`, `restore`, `verify-receipt`, `teardown`                                                                                     | Data is actually recoverable: row counts, latest timestamps, objects with metadata, offline start | [`dr-isolated-restore-1632.md`](dr-isolated-restore-1632.md) "Owner-run procedure" |
| **E. Schedule** (separate approval) | Owner                                                                                          | Enable the daily timer; later, the off-device copy cadence                                                                                                                       | Ongoing RPO                                                                                       | `dr-site-activation-1428.md` step 8                                                |

Stage 3 of the network work (#1734) needs a **fresh receipt from A2**, and the timing of any backend release needs **D**.

## Fingerprints to record (never the key)

```bash
# custody receipts (#1631) record this one:
sudo sha256sum /etc/nexolab/dr-backup.key
# bundle headers and backup receipts record this domain-separated key id:
sudo python3 -I -B -c 'import hashlib,sys; k=open(sys.argv[1],"rb").read(); print(hashlib.sha256(b"nexolab-dr-stream-key-id\x00"+k).hexdigest()[:32])' /etc/nexolab/dr-backup.key
```

Register line, for example: `2026-11-27 · key v1 · sha256=… · id=… · custodians: owner (Pi), <name> (stick, location X) · SSD A: location Y`.

## What the agent does and never does

- **Does:**
  - stages and pins packages from merged `main`;
  - runs read-only checks (`backup.health`);
  - runs approved `backup.start` through the Operator Broker and records the before, during and after metrics;
  - updates #1428 with receipts and fingerprints that the owner shares.
- **Never:**
  - reads, copies or displays the key or any secret;
  - mounts the owner's media;
  - performs the off-device copy or the restore;
  - enables the timer without approval;
  - deletes bundles.

## If something fails

- **A or A2 fails:** nothing in production changed. The unit is a oneshot at idle priority, and the rollback in the activation runbook removes only the units.
- **The key is lost before B:** delete nothing. Create a new key, take a new backup, and restart at B. Old bundles are unrecoverable without the old key.
- **D fails:** #1428 stays open. Keep the bundle and the receipts, and attach the restore receipt's failed checks to #1632.
