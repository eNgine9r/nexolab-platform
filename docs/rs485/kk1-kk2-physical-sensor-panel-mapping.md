# KK1 / KK2 physical sensor panel mapping

Issue: #966

Evidence date: 2026-09-08

Profile: `LOCAL_LAN`

## Authority boundary

This mapping records the current laboratory sensor connection panels supplied by
the Product Owner. It corrects catalog identity only. It does **not** prove that
every listed Modbus Unit ID currently answers on the field bus and it does not
authorize any Modbus write.

### KK1

The large numeric labels on the brown panel are the authoritative short sensor
identifiers. The small brown-strip `D.` / `K.` controller markings are known to
be incorrect and must not be used to remap telemetry.

The repository communication mapping remains six individual inputs per Dixell
Unit ID `126..138`, with one physical sensor per input:

```text
126-01 -> 197
126-02 -> 198
126-03 -> 199
126-04 -> 200
126-05 -> 201
126-06 -> 202
127-01 -> 203
...
138-06 -> 274
```

Formula:

```text
physical_sensor_number = 197 + (controller_unit_id - 126) * 6 + (input_number - 1)
```

The operator-facing short label is the numeric physical sensor number (for
example `200`), while `126-04` remains the canonical telemetry input identity.

### KK2

The blue panel is authoritative for both the large physical sensor number and
the `D.` / `K.` controller/input marking. The complete physical number range is
`441..554` and corresponds to 19 controllers `K96..K114`, six individual
inputs per controller.

Formula:

```text
physical_sensor_number = 441 + (controller_unit_id - 96) * 6 + (input_number - 1)
```

Representative mappings visible on the panel and/or implied by the confirmed
continuous endpoints are:

| Dixell | Inputs | Physical sensors |
| ------ | ------ | ---------------- |
| K96    | 1..6   | 441..446         |
| K101   | 1..6   | 471..476         |
| K106   | 1..6   | 501..506         |
| K114   | 1..6   | 549..554         |

The panel groups two individual inputs behind each physical connector label:

```text
D.<K>-01 -> K.<K> inputs 1/2
D.<K>-03 -> K.<K> inputs 3/4
D.<K>-05 -> K.<K> inputs 5/6
```

This grouping is connector metadata only. It does not collapse the six XJP60D
telemetry inputs into three values. For example K101 remains six canonical
channels `101-01` through `101-06`, whose short physical identifiers are
`471` through `476`.

## Superseded catalog assumption

Issue #173 / PR #174 modelled KK2 as K101..K114 with 84 logical channels and
two synthetic physical sensors (`A`/`B`) per channel. That produced identifiers
such as `471-A` and `471-B`. The physical panel establishes instead one physical
sensor per individual input and the earlier K96..K100 range.

Existing K101..K114 canonical telemetry channel IDs remain unchanged so their
historical samples and bindings are not silently re-keyed. The catalog data
migration retains the legacy `A` row as the single physical sensor, converts
its inventory number to the numeric panel identifier, and refuses migration if
a synthetic `B` row contains user metadata, audit history, or a discovery
reference.

## Runtime safety

Adding K96..K100 to catalog/discovery inventory does not add them to the active
continuous polling set. Any real read-only communication acceptance for those
controllers is a separate hardware/runtime validation step. Modbus writes,
address changes, rewiring, and site cutover remain prohibited without explicit
approval.
