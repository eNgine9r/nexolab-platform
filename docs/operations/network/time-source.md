# Reliable time for offline operation (#1734 WP2e)

## Evidence (2026-11-25, read-only)

- The host booted at 07:23:29Z, but the Device Agent recorded `started_at 05:47:18Z`. The wall clock started about 1 h 37 min behind and was corrected only after the new network gave internet NTP access. Samples taken before the correction carry wrong `captured_at` values.
- The Pi 5 RTC `rpi-rtc` exists and set the clock at boot (`/sys/class/rtc/rtc0/hctosys = 1`), but battery trickle charging is off (`charging_voltage = 0`). Losing time across the move means the RTC has no working backup battery, so the clock fell back to the last time saved by `systemd-timesyncd`.
- `systemd-timesyncd` uses the default servers only (no local NTP configured). Offline, nothing ever corrects the clock.

## Required (owner, physical and root)

1. **RTC backup battery.** Fit the Raspberry Pi RTC battery (rechargeable lithium manganese ML-2020 with the 2-pin JST plug). Only for that rechargeable cell, enable trickle charging in `/boot/firmware/config.txt` with `dtparam=rtc_bbat_vchg=3000000`. **Never enable charging for a non-rechargeable coin cell.** This takes effect at the next approved reboot.
2. **Local time source (if the laboratory has one).** Create `/etc/systemd/timesyncd.conf.d/nexolab.conf` containing `[Time]` and `NTP=<laboratory NTP server>`, keeping the default `FallbackNTP`. Then `sudo systemctl restart systemd-timesyncd`. Use the address of a server, never a host name that needs internet DNS.
3. Without either of these, an offline boot after power loss keeps the wrong time. The Device Agent now reports this instead of hiding it (below).

## Software guard (this Work Package)

Device Agent `/health` includes `clock: {synchronized, kernel_state, source}`, read by a read-only `adjtimex` call (no privilege, never changes the clock). `synchronized: false` means samples are being stamped by an undisciplined clock. `null` means the status is unavailable and must not be read as synchronized. This applies to new Device Agent builds; the commissioned site agent `nexolab/quick-agent:1490` is unchanged until a separately approved agent release.

## Verification

```bash
cat /sys/class/rtc/rtc0/hctosys /sys/class/rtc/rtc0/charging_voltage  # 1 and 3000000 after step 1
timedatectl show -p NTPSynchronized -p TimeUSec                          # NTPSynchronized=yes
timedatectl timesync-status                                              # server, offset, poll interval
journalctl -b -u systemd-timesyncd --no-pager | tail -5                  # first synchronization and any clock step
```

Acceptance: unplug power for at least 10 minutes with the network disconnected, boot offline, and confirm `date -u` is within a few seconds of a reference clock before any sample is published. Then reconnect and confirm `NTPSynchronized=yes` with no large step.
