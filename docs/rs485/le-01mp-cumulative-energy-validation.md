# LE-01MP cumulative active-energy hardware validation

- Issue: #201
- Date: 2026-08-17
- Runtime: accepted Raspberry Pi `LOCAL_LAN` deployment baseline `1d226d6ddcd0c009b8f83367599d7a64521190f0`

## Outcome

Normal-operation cumulative active-energy semantics are hardware-confirmed for installed LE-01MP Units `200–203`:

```text
Modbus function: 03 (read holding registers)
start address: 7
count: 2
word order: R7 high word, R8 low word
encoding: unsigned 32-bit
raw32 = (R7 << 16) | R8
scale: 0.01 kWh
metric: electrical.energy.active
unit: kWh
```

The two words are required to be read in one physical FC03 request.

## Safety controls used during probing

- the live Device Agent was stopped before opening the serial device from the probe;
- exclusive serial ownership was checked before every probe;
- probe requests were read-only FC03 only;
- no Modbus write path was used;
- no meter reset, address change, baud/parity change or electrical installation change occurred;
- the Device Agent was restarted and returned to `healthy` after the probes.

## Two-register frame evidence

Three repeated passes returned identical frames on all four units:

- Unit 200: R7 `20`, R8 `63791`, raw32 `1374511`, decoded `13745.11 kWh`.
- Unit 201: R7 `38`, R8 `49806`, raw32 `2540174`, decoded `25401.74 kWh`.
- Unit 202: R7 `17`, R8 `15498`, raw32 `1129610`, decoded `11296.10 kWh`.
- Unit 203: R7 `21`, R8 `2364`, raw32 `1378620`, decoded `13786.20 kWh`.

The decoded values matched the corresponding W1–W4 physical meter displays as observed by the Product Owner.

## Monotonicity evidence under live load

- Baseline timestamp: `2026-08-17T13:21:38Z`
- Follow-up timestamp: `2026-08-17T13:31:28.831758Z`

Observed follow-up behavior:

- Unit 200: `0 W`, `13745.11 -> 13745.11 kWh`, delta `+0.00 kWh`.
- Unit 201: `2520 W`, `25401.74 -> 25402.02 kWh`, delta `+0.28 kWh`.
- Unit 202: `228 W`, `11296.10 -> 11296.14 kWh`, delta `+0.04 kWh`.
- Unit 203: `0 W`, `13786.20 -> 13786.20 kWh`, delta `+0.00 kWh`.

This is consistent with a cumulative energy counter: loaded meters increased while meters at zero active power remained unchanged during the observation window.

## Communication observation

An earlier single-register probe produced temporary timeouts on Units 201 and 203. A subsequent control diagnostic read both production voltage register `0` and energy candidate register `7` successfully on all four units, and the two-register probe then completed with zero failures. The timeouts are therefore classified as transient communication evidence, not proof that energy registers are absent on those units.

## Remaining hardware boundary

This document does not claim reset, rollover or power-cycle semantics. Full Issue #201 hardware acceptance remains pending an approved restart/power-cycle observation. Until then, any decrease in the cumulative counter must be treated as a discontinuity/reset/rollover candidate rather than silently transformed into positive consumption.
