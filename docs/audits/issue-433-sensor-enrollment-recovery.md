# Issue #433 sensor enrollment and recovery audit

## Before-change Raspberry Pi baseline

Captured on 2026-08-13 from repository head
`aa8c8fc2a4a3d496c4e9d6bfaa49ac284f4f2b2c` before product-code changes.
All hardware interaction was read-only Modbus FC03. No controller, sensor,
serial, registry, or other persistent-data writes were performed.

- Host: `nexolab-edge-01`, Linux `6.18.39+rpt-rpi-2712`, `aarch64`.
- Device Agent: `nexolab-edge-device-agent-1`, healthy, with one adaptive
  `rs485-main` worker and 33 poll-eligible targets.
- Stable transport: the configured
  `/dev/serial/by-id/usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_0133F090-if00-port0`
  resolved to `/dev/ttyUSB0`.
- Registry: schema 1, revision 2, 31 devices, 194 targets, 33 poll eligible;
  33 target lifecycles were `active` and 161 were `discovery_only`.
- XJP60D inventory contained configured Unit IDs 101-114 and 126-138. Unit
  126 was the only active XJP60D device and `xjp60d:126-04` the only active
  XJP60D target.
- The bounded manual discovery completed at
  `2026-08-13T12:11:32.115367+00:00` in 62,591 ms. It scanned 27 configured
  controllers, found 13 responsive controllers, one valid point
  (`126-04`, 25.0 degC, high alarm), 77 channel-level unavailable results,
  and 14 controller timeouts.
- Normal acquisition metrics after discovery: 65,106 physical requests,
  4,613 retry attempts, 60,384 successes, 4,720 timeouts, and 2 protocol
  errors. Discovery remained a separately attributed service operation with
  674 physical requests, 336 retry attempts, 308 successes, 364 timeouts,
  and 2 exception responses.
- Scheduler policy remained unchanged: high/medium/low intervals 5/10/30 s,
  failure threshold 3, cooldown 30-300 s. One endpoint was in cooldown while
  the other targets continued under the single bus worker.
- Latest edge acquisition for `xjp60d:126-04` was valid at
  `2026-08-13T12:24:28.393214+00:00`. Historical targets
  `xjp60d:102-01`, `xjp60d:102-02`, and `xjp60d:104-03` retained their last
  successful values from 2026-08-11 while truthfully reporting later
  `communication_error` attempts on 2026-08-13.
- Bounded 30-minute Device Agent logs contained endpoint timeouts for LE01MP
  Unit 201 at cooldown-spaced intervals. They contained no `termios`, serial
  handle, missing-device, or I/O transport errors.

## Separate failure classification

1. **Known sensor/channel activation and first-sample state.** Existing
   inventory activation already updates the canonical registry and the
   running adaptive scheduler. The UI, however, derives its channel cards
   only from received telemetry and therefore cannot represent an active
   target before its first attempt/sample; it can misleadingly render the
   empty state as no active channels.
2. **New Unit ID missing from the persisted registry.** This was not an
   active physical omission in the captured scan: all 27 configured discovery
   Unit IDs were already inventory members. The repository-backed defect is
   deterministic: discovery units are imported only during initial migration,
   subsequent startups load the persisted registry unchanged, discovery saves
   only its result, and lifecycle mutations reject unknown devices/targets.
   A later configured and responsive Unit ID therefore has no safe enrollment
   handoff.
3. **Transient endpoint communication loss.** Per-target latest state and
   bounded logs show timeouts independently of healthy targets. The existing
   scheduler already isolates endpoints, applies bounded cooldown, and resumes
   on normal scheduled attempts. No retry-policy increase is warranted.
4. **USB/serial transport loss.** No transport loss was observed in this
   baseline. The stable by-id path and serial handle recovery delivered by
   #378 remain the governing mechanism and are not redesigned by #433.

## Proven implementation gap

The focused change must extend the existing #284 registry with an atomic,
audited, read-only-profile enrollment operation invoked only after a successful
explicit discovery. Responsive new XJP60D units must enter as
`discovery_only`; enrollment alone must add no scheduler jobs. Explicit
operator activation must continue through the existing registry mutation and
#285 scheduler reconciliation. The existing latest/scheduler read model must
also expose bounded target state so the UI can distinguish initialization,
sensor error, communication error, cooldown, recovery, and valid freshness.
The #378 transport implementation and retry values remain unchanged.

## Implemented recovery path

- Explicit read-only discovery now hands responsive configured XJP60D Unit IDs
  to the existing acquisition registry. New devices and all six catalogued
  targets are inserted atomically at one new registry revision with an audit
  entry and `discovery_only` lifecycle.
- Enrollment rejects non-integer/out-of-range Unit IDs, duplicate bus/Unit
  identities owned by another family, unsupported profiles and every function
  other than the existing FC03 profile. An idempotent rediscovery does not
  create another revision or audit entry.
- The existing operator-approved active-point mutation remains the only path
  to `active`. The adaptive scheduler reconciles that canonical registry after
  discovery and activation, adds no job for discovery-only inventory, and
  schedules a newly activated target on the existing bounded startup deadline.
- The existing latest-value store now retains bounded per-target attempt,
  success, communication-failure, consecutive-failure and recovery metadata.
  The scheduler exposes these counters with last attempt/success, cooldown and
  next-deadline state for active XJP60D targets.
- Overview and sensor-management UI now distinguish initialization before the
  first attempt, sensor error, communication error, cooldown and recovery.
  Stale/error samples remain non-live and there is no demo fallback.

## Software verification

Verified locally on 2026-08-13 from the recovered Issue #433 working tree:

- focused Device Agent registry/scheduler/runtime tests: 30 PASS;
- complete Device Agent suite: 120 PASS, including stable-path EIO/termios
  handle recovery and UI acquisition-boundary invariants;
- focused dashboard tests: 4 PASS;
- complete frontend suite: 89 files / 384 tests PASS, including lint-staged
  transaction tests;
- Prettier repository check, ESLint and TypeScript typecheck: PASS;
- Next.js production build: PASS.

The implementation does not change scheduler intervals, failure thresholds,
cooldown values, retry counts, discovery breadth or browser-driven acquisition
behavior. It adds no Modbus/hardware write path and performs no persistent-data
deletion or site cutover.

## Hardware classification

The before-change Raspberry Pi baseline above is the only physical evidence in
this Work Package checkpoint. No post-change deployment, unplug/replug, sensor
manipulation or Raspberry Pi acceptance was performed, so post-change physical
enrollment/recovery remains explicitly unverified. Exact-head GitHub and
offline/browser workflow evidence is recorded on the focused Pull Request.
