# Issue #200 — current physical RS-485 topology evidence

Updated: 2026-08-23
Profile: `LOCAL_LAN`
Host: `nexolab-edge-01`

## Evidence boundary

This document records only observations obtained from the running NEXOLAB host, Linux device inventory, the existing production Device Agent diagnostics, and the persisted acquisition registry. No independent Modbus scanner or second master was started. No Modbus write, hardware write, wiring change, service restart, or site cutover was performed.

Raw host snapshots are retained outside Git under:

```text
runtime/evidence/issue-200-passive-20260823T070935Z
```

They contain Device Agent health/diagnostic state only; no credentials, environment files, or production telemetry values are committed here.

## Verified host adapter inventory

At the observation time Linux exposed exactly one USB serial adapter:

```text
/dev/serial/by-id/usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_0133F090-if00-port0
  -> /dev/ttyUSB0
USB VID:PID 10c4:ea60 — Silicon Labs CP210x UART Bridge
```

No second `/dev/ttyUSB*` or `/dev/ttyACM*` adapter was present.

The running Device Agent was healthy and bound to the same stable adapter identity with the following non-secret Modbus RTU settings:

```text
DEVICE_MODE=modbus
SERIAL_BAUDRATE=9600
SERIAL_PARITY=N
SERIAL_STOPBITS=1
SERIAL_TIMEOUT_SECONDS=0.30
SERIAL_RETRIES=1
```

Therefore the currently deployed hardware is a **single physical adapter / single logical `rs485-main` runtime**, not the two-adapter `rs485-kk1` + `rs485-kk2` topology required for Issue #607 hardware acceptance.

## Persisted registry snapshot

Device Agent registry revision at observation: `10`.

Persisted registry bus:

```text
bus_id: rs485-main
protocol: modbus_rtu
read_only: true
```

Non-discovery devices recorded in the registry:

| Family  | Unit ID | Lifecycle | Bus        |
| ------- | ------: | --------- | ---------- |
| XJP60D  |     102 | active    | rs485-main |
| XJP60D  |     104 | active    | rs485-main |
| XJP60D  |     106 | active    | rs485-main |
| XJP60D  |     108 | active    | rs485-main |
| XJP60D  |     126 | active    | rs485-main |
| LE-01MP |     200 | active    | rs485-main |
| LE-01MP |     201 | disabled  | rs485-main |
| LE-01MP |     202 | active    | rs485-main |
| LE-01MP |     203 | active    | rs485-main |

Discovery-only Unit IDs recorded in the persisted registry:

```text
101, 103, 105, 107, 109, 110, 111, 112, 113, 114,
127, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138
```

### Unit ID 115

Unit ID `115` is absent from both the persisted device list and target list at registry revision `10`. This proves **registry absence only**. It does not prove physical absence from the field bus because no new read-only scan was initiated while the production Device Agent remained the active Modbus master.

## Passive 60-second acquisition envelope

Observation window:

```text
2026-08-23T07:09:35Z -> 2026-08-23T07:10:35Z
```

Only `/health` snapshots were read before and after the window. The production scheduler continued normal acquisition and `service_operations` stayed empty at both boundaries.

| Metric                                     | 60 s delta / observation |
| ------------------------------------------ | -----------------------: |
| Physical requests                          |                     +402 |
| Successful requests                        |                     +306 |
| Timeout outcomes                           |                      +96 |
| Retry attempts                             |                      +96 |
| Persisted/produced samples at Device Agent |                     +210 |
| Missed deadlines                           |                     +122 |
| Deadline-skipped work                      |                       +0 |
| Deferred work                              |                      +10 |
| Bus load                                   |       75.591% -> 76.942% |
| Queue depth at end                         |                        1 |
| Worker state at end                        |                  running |

Derived observation rates:

- physical request rate: approximately `6.70 requests/s`;
- successful request rate: approximately `5.10 requests/s`;
- timeout/retry rate: approximately `1.60 requests/s`;
- timeout share of physical requests in this window: approximately `23.9%`;
- sample production rate: approximately `3.50 samples/s`.

This window does **not** justify increasing polling frequency. The current single bus is already heavily utilized and records substantial XJP60D retry/timeout work. Any faster cadence must remain subject to the authoritative capacity validator and real hardware acceptance.

## Longer-running diagnostic context

The same production Device Agent reported one healthy serialized worker for `rs485-main`, no worker failures/restarts, and bus load around 75–77%. Accumulated XJP60D target diagnostics show repeated timeout/retry behavior, while LE-01MP 200/203 are predominantly successful and LE-01MP 202 has only sparse timeout/protocol-error events.

These counters are useful evidence of the current operating envelope, but they are not a substitute for a controlled per-bus test after the intended dual-adapter topology exists.

## What is verified

- one stable CP2104 adapter identity exists on the current Raspberry Pi;
- production uses `9600 8N1`, `0.30 s` timeout, one retry;
- the running Device Agent is read-only and owns one logical `rs485-main` worker;
- the persisted active/discovery topology is known at registry revision `10`;
- Unit ID `115` is not present in the persisted registry;
- the current single-bus acquisition load and request/retry envelope have a bounded passive observation;
- no parallel Modbus master or service operation was introduced by this evidence capture.

## Still hardware-unverified / blocked

The following Issue #200 acceptance criteria cannot be claimed from remote software evidence:

- physical presence or absence of Unit ID `115` on the field wiring;
- duplicate Unit IDs that may exist electrically but are not represented in the registry;
- cable route/topology, termination, biasing, shielding, and grounding observations;
- two-adapter KK1/KK2 physical isolation: only one adapter is currently enumerated;
- per-bus simultaneous polling and one-bus-disconnect isolation;
- reboot-stable mapping for two physical adapters.

A future field step must not start an independent scanner while the production Device Agent is polling the same segment. Safe read-only scanning requires either a controlled pause/maintenance procedure or the intended isolated second-bus arrangement, with explicit approval for any production/hardware-affecting action.

## Safety status

```text
Modbus writes: none
Hardware writes: none
Production/site cutover: not performed
Independent Modbus scanner: not started
Production Device Agent restart: not performed
Persistent data deletion: none
```

## 2026-08-28 planned Bus 2 commissioning

The Product Owner has a second USB–RS-485 adapter available and intends to use the new isolated physical bus for a refrigerated-display controller plus an XJP60D analog acquisition module.

The intended signal boundary is:

```text
Raspberry Pi 5
├─ existing Bus 1 -> current production RS-485 devices
└─ candidate Bus 2 -> refrigerated-display controller (read-only Modbus)
                   -> Dixell XJP60D (read-only Modbus)
                        ├─ pressure transmitter 4-20 mA
                        ├─ Rheonik / flow signal 4-20 mA, if verified
                        └─ relative-humidity transmitter 4-20 mA
```

The 4–20 mA instruments are **not** RS-485 nodes. They terminate on compatible XJP60D analogue inputs; NEXOLAB reads the XJP60D over RS-485. Exact input capability, scaling and instrument semantics remain hardware/profile evidence and must not be inferred from the controller name.

A host-side helper is provided at:

```text
services/device-agent/tools/commission_rs485_bus.py
```

Its default action only inventories `/dev/serial/by-id/` and stores sanitized adapter evidence. An active scan requires explicit `--scan`; the helper refuses the existing production adapter, fails closed if the selected port is already owned by another process, and delegates discovery to the existing read-only scanner (`FC03`, `FC04`, `43/14` only).

Example inventory after inserting the second adapter:

```bash
python3 services/device-agent/tools/commission_rs485_bus.py \
  --existing-port /dev/serial/by-id/usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_0133F090-if00-port0
```

After the new stable path is identified and Bus 2 contains only the intended isolated segment, run bounded read-only discovery:

```bash
python3 services/device-agent/tools/commission_rs485_bus.py \
  --existing-port /dev/serial/by-id/usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_0133F090-if00-port0 \
  --adapter /dev/serial/by-id/<NEW_ADAPTER> \
  --scan
```

The helper writes evidence under `runtime/evidence/rs485-bus2-<UTC timestamp>/` and **does not** activate `RS485_BUS_CONFIG_JSON`, mutate the acquisition registry, restart Device Agent, change controller configuration, or perform a production cutover. Those actions remain gated by review of the discovery evidence and explicit hardware acceptance.
