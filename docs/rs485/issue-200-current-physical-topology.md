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

## 2026-08-28 Bus 2 adapter insertion evidence

The second USB–RS-485 adapter was physically inserted without A/B field wiring attached. Linux now exposes two independent stable CP2104 identities:

```text
Bus 1: /dev/serial/by-id/usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_0133F090-if00-port0
       -> /dev/ttyUSB0
Bus 2: /dev/serial/by-id/usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_0133F246-if00-port0
       -> /dev/ttyUSB1
```

Both adapters report USB VID:PID `10c4:ea60`, driver `cp210x`; the unique serial numbers are `0133F090` and `0133F246`. The new Bus 2 adapter is also independently addressable through its physical USB path (`xhci-hcd.0`, USB port `1-2`). No process owned either stable serial path during the inventory check.

The commissioning helper recorded sanitized inventory evidence under `runtime/evidence/issue-200-bus2-inventory/rs485-bus2-20260828T105924Z/adapters.json`. No Modbus request was sent because A/B remained disconnected. Bus 2 therefore advances from `adapter absent` to `adapter present / field bus unverified`; controller and XJP60D communication remain hardware-unverified until the isolated A/B segment is connected and read-only discovery is explicitly started.

## 2026-08-28 Bus 2 first energized read-only discovery

After the Product Owner energized the second adapter and connected the test Bus 2 segment, the adapter re-enumerated at the same stable identity `0133F246 -> /dev/ttyUSB1` and was not owned by another process.

A bounded read-only quick discovery scanned unit IDs `1..247` across `9600 8N1`, `9600 8E1`, `19200 8N1` and `19200 8E1`. Only Modbus functions `03`, `04` and `43/14` were used; no register writes or controller configuration changes were performed.

Result:

```text
valid endpoints: 0
warnings:        988 / 988 probe positions
```

Every warning contained received bytes without a valid CRC frame. A targeted raw read on units 1 and 6 then showed exactly one received byte `0x00` after each request on all four quick serial profiles. A one-second passive listen on each profile produced zero bytes.

This pattern is treated as **physical-layer failure evidence**, not as evidence that the Modbus addresses are absent. The current leading checks are A/B polarity, transceiver/field wiring and common reference/GND requirements. Duplicate unit IDs are a lower-probability explanation because the observed receive pattern is a single deterministic `0x00` after transmission rather than overlapping valid-length replies.

Evidence directory: `runtime/evidence/rs485-bus2-20260828T122942Z/`. Production Bus 2 remains inactive and hardware acceptance remains unverified.

## 2026-08-28 Embraco Sync isolated Bus 2 evidence

The Bus 2 segment was reduced to the Embraco Sync controller only. The controller HMI showed `Mb0=096`, `Mb1=096`, `Mb2=001`; the uploaded v1.00.04 manual defines the Modbus interface as parity `None`, selectable baud rate, slave address and one/two stop bits.

Read-only discovery on the second stable adapter (`0133F246`) found a CRC-valid endpoint at `9600 8N1`, unit ID `96`. Strict verification confirmed the same endpoint with FC03 and no write function was issued.

Using the manual's read register map, FC03 addresses `0..12` were sampled one register per request, three passes. All 13 registers answered successfully in every pass. Observed signed values were:

```text
0=20, 1=4, 2=0, 3=2626/2626/2630, 4=0, 5=0, 6=0,
7=0, 8=2, 9=5, 10=2, 11=4500, 12=0
```

Per the manual, address 9 is cooling control state (`5 = Pulldown`), address 10 is the relay-state bitfield, address 11 is VCC compressor speed, and address 12 is the alarm bitfield. Thus this snapshot reports Pulldown state, relay bitfield `2`, compressor speed `4500`, and no active alarm bits. Temperature/register scaling remains to be correlated against physical/display evidence before production semantics are declared.

Raw discovery, strict-verification and register-profile artifacts remain under `runtime/evidence/` and are intentionally not used to activate production Bus 2. No controller parameters, setpoints, relays, baud rate or slave address were written or changed.
