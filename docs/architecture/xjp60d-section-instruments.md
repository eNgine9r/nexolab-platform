# Section-addressed XJP60D instruments

Issue1500 follows isolated and combined FC03 hardware evidence on2026-11-05.
The first physical module uses addresses1–6 with six attached probes; the second
uses7–12 with two attached probes and four operator-declared reserve inputs.

The legacy `dixell-xjp60d` profile remains a single-address, six-register-pair
contract. A common register response never selects a section profile automatically.
The operator explicitly chooses section mode, the first address, and the count
of attached consecutive first inputs. Internal fixed profiles1–6 persist this
choice through the existing versioned commissioning profile contract, without
adding a schema or a second configuration authority.

Each section instrument owns six consecutive addresses within one node/bus.
The registry reserves the entire range, including unattached inputs, and rejects
overlapping ownership. Active targets read registers256/257 using FC03 at
`first_address + input_number - 1`. Reserve targets are not continuously polled.
Preflight reads all six sections and requires each declared attached probe to be
valid. This does not establish physical health of unattached probes.

Section telemetry uses source `dixell-xjp60d-sections`, equipment identity
`XJP60D-S:<bus>:<first_address>` and channel `<bus>:<first_address>-S<01..06>`.
These separate current section data from ambiguous historical K1/K2 records.
Historical telemetry is never relabeled. Cards show one saved physical instrument,
its range, configured attached count and reserve count; actual freshness and
threshold states remain properties of readings, not activation status.

Changing attached count is an explicit profile change through controlled
deactivation/re-enrollment, never an inferred result of probe errors. Test-site
replacement of obsolete intents/registry entries requires retained prior state,
explicit bounded identities and an audit/checkpoint. It is not a Modbus write.
