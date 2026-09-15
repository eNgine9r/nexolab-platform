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

`oa1` and `oa2` are not yet confirmed on this physical unit and must not be guessed. The documentation defines `oa1` as baud-rate selection and `oa2` as parity/stop-bit selection.

## Communication settings from Danfoss

- `oa1=1` Auto, `2` 9600, `3` 19200, `4` 38400, `5` 115200 baud.
- `oa2=0` None, `1` Even, `2` Odd. The supplied guide does not explicitly define the non-default stop-bit count, so NEXOLAB does not infer it.
- The SW 1.3x Modbus guide states default communication speed is auto detection and the default framing is **8 data bits, Even parity, 1 stop bit (`8E1`)**.

NEXOLAB must read the actual physical `oa1`/`oa2` values before selecting a production bus. No controller communication parameter may be changed as part of this work package.

## Fixed FC03 discovery subset

The first probe uses FC03 only. It reads a bounded set of documented **R** integer service registers plus `o03` / `oa1` / `oa2` in read-only mode so the physical communication configuration can be observed without mutation. Decimal/temperature `Float` values are excluded until their exact on-wire representation is confirmed on the real controller.

| Key                | Danfoss code | Modbus ADU |  Range | Meaning                                                     |
| ------------------ | ------------ | ---------: | -----: | ----------------------------------------------------------- |
| `control_state`    | `u00`        |       2007 |   0–55 | controller state code                                       |
| `compressor_state` | `u58`        |       2510 |    0–1 | compressor 1 OFF/ON                                         |
| `compressor_speed` | `u52`        |       2685 |  0–100 | compressor speed, %                                         |
| `fan_state`        | `u59`        |       2511 |    0–1 | evaporator fan OFF/ON                                       |
| `defrost_state`    | `u60`        |       2512 |    0–1 | defrost A OFF/ON                                            |
| `network_status`   | `U45`        |       2682 |  0–100 | network status, %                                           |
| `alarm_status`     | `x16`        |       2541 |    0–1 | alarm status OFF/ON                                         |
| `network_address`  | `o03`        |       2008 | -1–240 | configured network address; read-only observation           |
| `baudrate_setting` | `oa1`        |       2251 |    1–5 | Auto / 9600 / 19200 / 38400 / 115200; read-only observation |
| `parity_setting`   | `oa2`        |       2255 |    0–2 | None / Even / Odd; read-only observation                    |

## Explicit exclusions

The programming guide also exposes many `RW` registers and commands. NEXOLAB does **not** use them in this profile. In particular, this work package must not change setpoints, `o03`, `oa1`, `oa2`, application configuration, compressor/fan overrides, manual defrost, alarm reset or any output.

The discovery profile is marked `activation_supported=False`. A successful preflight therefore does not enroll the device into production polling.

## Hardware acceptance gate

Current status: `hardware_unverified`.

To promote this profile, evidence must show all of the following at the exact source SHA:

1. Actual `oa1` and `oa2` values observed on the physical Unit 35 without modifying them.
2. Single-master RS-485 topology with a stable `/dev/serial/by-id/...` adapter identity.
3. Valid FC03 response from Unit 35 for the fixed read-only subset.
4. At least one returned value correlated with the front display or an observable controller state.
5. Existing `rs485-main` and `rs485-embraco` acquisition remain healthy.

Temperature service registers such as `u56` display readout are documented by Danfoss but remain outside this first software probe until physical decoding evidence is captured.
