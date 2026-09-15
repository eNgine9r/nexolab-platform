# Danfoss AK-CC25 Pro — read-only discovery profile

Issue: #1024

Physical model observed: **AK-CC25 Pro, 084B4022**

Repository profile: `danfoss-ak-cc25-pro-sw1.3x-fc03-v1`

## Authoritative documentation

- Danfoss Programming Guide / Modbus interface description `AU531131049269en-000201`, SW 1.3x (2026.01), supplied by the Product Owner.
- Danfoss data sheet `AI539523026164en-000101` (2025.11), supplied by the Product Owner; product code table confirms AK-CC25 Pro `084B4022`.

The programming guide explicitly covers product codes `084B4022` and `084B4023` and states that AK-CC25 Pro uses Modbus RTU.

## Physical controller facts

The Product Owner confirmed `o03 = 35` on the physical controller. Danfoss defines `o03` as the Modbus/network address, so the intended Unit ID is **35**.

`oa1` and `oa2` are now confirmed by a real read-only maintenance probe: `oa1=1` (Auto) and `oa2=1` (Even). No controller parameter was changed.

## Communication settings from Danfoss

- `oa1=1` Auto, `2` 9600, `3` 19200, `4` 38400, `5` 115200 baud.
- `oa2=0` None, `1` Even, `2` Odd. The supplied guide does not explicitly define the non-default stop-bit count, so NEXOLAB does not infer it.
- The SW 1.3x Modbus guide states default communication speed is auto detection and the default framing is **8 data bits, Even parity, 1 stop bit (`8E1`)**.

Real Unit 35 evidence confirms a valid response at **9600 8E1** while the controller reports `oa1=1` (Auto) and `oa2=1` (Even). No controller communication parameter may be changed as part of this work package.

## Fixed FC03 discovery subset

The probe uses FC03 only. Danfoss publishes one-based **Modbus ADU** numbers; real Unit 35 evidence proved that the FC03 request address is the zero-based PDU register address `ADU - 1`. The probe reads a bounded set of documented **R** integer service registers plus `o03` / `oa1` / `oa2` in read-only mode so the physical communication configuration can be observed without mutation.

| Key                | Danfoss code | Modbus ADU | FC03 PDU address | Wire type / scale | Unit    | Meaning                                                     |
| ------------------ | ------------ | ---------: | ---------------: | ----------------- | ------- | ----------------------------------------------------------- |
| `control_state`    | `u00`        |       2007 |             2006 | uint16 / ×1       | state   | controller state code                                       |
| `compressor_state` | `u58`        |       2510 |             2509 | uint16 / ×1       | state   | compressor 1 OFF/ON                                         |
| `compressor_speed` | `u52`        |       2685 |             2684 | uint16 / ×1       | %       | compressor speed                                            |
| `fan_state`        | `u59`        |       2511 |             2510 | uint16 / ×1       | state   | evaporator fan OFF/ON                                       |
| `defrost_state`    | `u60`        |       2512 |             2511 | uint16 / ×1       | state   | defrost A OFF/ON                                            |
| `network_status`   | `U45`        |       2682 |             2681 | uint16 / ×1       | %       | network status                                              |
| `alarm_status`     | `x16`        |       2541 |             2540 | uint16 / ×1       | state   | alarm status OFF/ON                                         |
| `network_address`  | `o03`        |       2008 |             2007 | int16 / ×1        | address | configured network address; read-only observation           |
| `baudrate_setting` | `oa1`        |       2251 |             2250 | uint16 / ×1       | enum    | Auto / 9600 / 19200 / 38400 / 115200; read-only observation |
| `parity_setting`   | `oa2`        |       2255 |             2254 | uint16 / ×1       | enum    | None / Even / Odd; read-only observation                    |

## Explicit exclusions

The programming guide also exposes many `RW` registers and commands. NEXOLAB does **not** use them in this profile. In particular, this work package must not change setpoints, `o03`, `oa1`, `oa2`, application configuration, compressor/fan overrides, manual defrost, alarm reset or any output.

The discovery profile is marked `activation_supported=False`. A successful preflight therefore does not enroll the device into production polling.

## Hardware acceptance gate

Current status: **read-only discovery hardware-verified; production activation remains disabled.**

Hardware acceptance was completed first through a controlled maintenance handoff and then repeated on a dedicated third adapter. All five discovery gates below are proven:

1. Actual `oa1` and `oa2` values observed on the physical Unit 35 without modifying them.
2. Single-master RS-485 topology with a stable `/dev/serial/by-id/...` adapter identity.
3. Valid FC03 response from Unit 35 for the fixed read-only subset.
4. A returned value is correlated with the front panel: `o03=35` was observed on the controller and returned as `35` over FC03. The service-state values are retained as telemetry evidence but are not used to validate temperature semantics while sensors/equipment are absent.
5. Existing `rs485-main` and `rs485-embraco` acquisition remain healthy.

A bounded read-only temperature experiment returned register data, but the controller had no temperature sensors connected. Those raw values are retained only as diagnostic evidence and are explicitly **not** interpreted as °C. Temperature semantics remain a follow-up hardware-correlation gate after real sensors are installed.

### 2026-09-15 real hardware evidence

- Controller: physical AK-CC25 Pro `084B4022`, Unit `35`.
- Dedicated adapter: `/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A10Q2SI7-if00-port0` (FT232R, serial `A10Q2SI7`).
- Existing production adapters stayed protected and active: CP2104 `0133F090` (`rs485-main`) and CP2104 `0133F246` (`rs485-embraco`).
- Confirmed serial profile: `9600 8E1`; controller reported `o03=35`, `oa1=1` (Auto), `oa2=1` (Even).
- The first dedicated-adapter pass had partial timeouts immediately after connection; the next three bounded FC03 passes returned the full fixed subset successfully.
- Post-probe Device Agent health remained `ok`, queue depth `0`, with both existing workers `running`; `rs485-main` and `rs485-embraco` continued normal traffic.
- Modbus writes, hardware writes, controller parameter changes and production activation: **none**.
