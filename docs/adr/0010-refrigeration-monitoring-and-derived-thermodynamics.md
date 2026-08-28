# ADR 0010: Refrigeration monitoring and derived thermodynamics

- Status: Accepted
- Date: 2026-08-28
- Decision owners: Product Owner, NEXOLAB engineering
- Profile: `LOCAL_LAN`
- Work Package: Issue #715 / RFX-00

## Context

NEXOLAB already has production refrigeration-equipment lifecycle, image/layout persistence,
sensor placement, climate-chamber measurement channels, structural snapshots and a canonical
telemetry envelope. Those contracts are useful, but the current refrigeration binding model is
primarily a UI/equipment placement relationship: equipment is bound to a physical telemetry
`node_id + channel_id` and a front/rear shelf slot.

The next refrigeration-monitoring scope adds process measurements that are not interchangeable:
refrigerated-product temperatures, suction and high-side pressure, suction-line and liquid-line
temperature, atmospheric pressure and relative humidity. Some physical instruments expose
4–20 mA signals and can reach NEXOLAB through different acquisition devices or converters.

The same acquisition-device family name must not imply the process meaning of its channel. A
Dixell XJP60D temperature-oriented profile and a physically supported XJP60D analog 4–20 mA
profile are different capabilities. Unsupported analog/register behavior remains hardware
unverified until exact model/profile documentation and real-device evidence exist.

The required thermodynamic values also depend on relationships between several measurements.
Evaporation/boiling saturation temperature, condensation saturation temperature, superheat and
subcooling must therefore be deterministic derived metrics with explicit refrigerant, pressure
reference, freshness, quality and provenance contracts. They must never be fabricated from a
single generic sensor value or a guessed refrigerant.

Core runtime remains local and offline-capable. No mandatory cloud refrigerant API, paid service,
remote telemetry service, CDN or internet dependency may be introduced. Acquisition remains
read-only; this decision creates no Modbus write or hardware-control path.

## Decision

Adopt an explicit refrigeration instrumentation and calculation domain layered over the existing
canonical telemetry pipeline:

```text
Asset
  → Acquisition Device
  → Instrument
  → Signal
  → Binding
  → Refrigeration Circuit
  → Derived Metric
```

These are ownership boundaries, not necessarily one database table each. Follow-up Work Packages
may map them onto existing tables or new normalized persistence, but API and calculation semantics
must preserve the distinctions in this ADR.

### 1. Asset and acquisition-device boundaries

An **Asset** is the monitored physical object or environmental reference whose state matters to
the operator. Existing `refrigeration_equipment` remains the current refrigeration-equipment
asset record and is not replaced by this ADR.

An **Acquisition Device** is the hardware/software endpoint that digitizes or transports a signal.
Examples include a validated XJP60D temperature-controller profile, a physically supported
XJP60D analog-input profile, an isolated analog-input/converter, or another accepted read-only
measurement device. Acquisition-device identity owns transport/profile facts such as bus,
protocol, unit address, channel and supported profile version; it does not own process meaning.

A controller family may expose multiple capabilities only when those capabilities are separately
versioned and evidenced. A display name containing `XJP60D` is insufficient evidence that a
specific physical unit accepts a particular 4–20 mA input or register mapping.

### 2. Instrument

An **Instrument** is the physical metrological source of one or more engineering measurements.
It owns physical identity and measurement metadata such as instrument type, manufacturer/model
when known, serial/inventory identity, calibration state, engineering range and pressure
reference type where applicable.

Required instrument classes include temperature probe, pressure transmitter, relative-humidity
transmitter and atmospheric-pressure sensor/reference. Future flow or other analog instruments
use the same model rather than creating controller-specific business entities.

### 3. Signal and process role

A **Signal** is a typed observable engineering value produced by an instrument after the accepted
acquisition/scaling path. It has a metric type, engineering unit, source/acquisition identity,
quality and timestamp. Existing `measurement_channels` and canonical telemetry events remain the
current transport/read-model basis for physical signals.

A signal's physical metric and its process role are separate concepts. For example, a pressure
signal measured in `bar` may be bound as `suction_pressure`, `condensing_pressure` or another
future role. A temperature signal in `degC` may be bound as `suction_line_temperature`,
`liquid_line_temperature`, ambient temperature or a refrigerated-product probe.

The minimum refrigeration process roles are:

- `suction_pressure`;
- `condensing_pressure`;
- `suction_line_temperature`;
- `liquid_line_temperature`;
- `atmospheric_pressure`;
- `relative_humidity`;
- existing product/cabinet temperature roles.

Roles must have a declared compatible physical metric/unit family. A pressure channel cannot be
silently bound as humidity or temperature merely because it comes from the same acquisition
device.

### 4. Binding

A **Binding** connects one accepted signal to one semantic role in an Asset or Refrigeration
Circuit. It owns assignment, validity interval and operator/audit provenance; it does not copy or
rewrite raw telemetry.

Existing `refrigeration_sensor_bindings` remain valid for current cabinet/product temperature
placement. They are not generalized in place during RFX-00. A follow-up migration may preserve
them as a placement-specific compatibility view while introducing a broader semantic binding
contract for process instruments and circuit roles.

A semantic binding must reference the canonical signal identity rather than infer meaning from a
human label. Historical validity is required so calculations and laboratory evidence can resolve
which signal occupied a role at a given time.

For a given organization, refrigeration circuit and semantic role, accepted binding validity
intervals must not overlap. Binding validity uses half-open interval semantics
`[valid_from, valid_to)`, with `valid_to = null` representing an open-ended interval. Therefore a
handover may set the previous `valid_to` equal to the replacement `valid_from`; at that exact instant
the previous binding is no longer valid and the replacement is valid. Resolution at any calculation
`observation_at` must return exactly one accepted signal for each required role. Zero resolvable
bindings makes the derived metric `unavailable`; more than one is an invalid/ambiguous configuration
and also fails closed as `unavailable` rather than selecting arbitrarily. Historical import or
migration must preserve this non-overlap/half-open invariant or quarantine the ambiguous interval
until explicitly reconciled.

### 5. Refrigeration circuit

A **Refrigeration Circuit** is the calculation boundary that owns thermodynamic configuration and
role assignments. At minimum it belongs to an organization and one monitored refrigeration asset
or explicitly versioned asset set, and it owns:

- stable circuit identity and display name;
- lifecycle/status metadata;
- explicit refrigerant profile reference;
- bindings for required low-side/high-side pressure and line-temperature roles;
- optional environmental/reference bindings;
- calculation-policy version.

Refrigerant identity is configuration, never an inference from equipment name, pressure,
temperature or controller identity. Changing refrigerant or calculation policy creates a new
versioned configuration boundary; historical results retain the configuration/provenance used at
calculation time.

Authoritative circuit configuration history uses non-overlapping half-open validity intervals
`[valid_from, valid_to)`, with `valid_to = null` for the current open-ended version. A normal or
historical calculation resolves the **single circuit/configuration version effective at
`observation_at`** using `valid_from <= observation_at < valid_to` (or no upper bound when
`valid_to = null`). Zero or multiple effective versions is invalid configuration and makes derived
metrics `unavailable`; implementations must not silently fall back to the current version. A
replay may carry an explicit configuration-version identifier only when that version is the one
effective at the requested `observation_at`; what-if calculations against another version are a
separate non-authoritative capability and must not be persisted as canonical derived history.

### 6. 4–20 mA acquisition

`4–20 mA` is an electrical signal class, not a refrigeration metric. The canonical acquisition
chain is:

```text
physical instrument → 4–20 mA → analog input/converter → read-only digital acquisition
                    → calibrated engineering value → canonical telemetry signal
```

The architecture permits more than one analog acquisition device. The intended special XJP60D
4–20 mA path can support the humidity transmitter only after the exact physical XJP60D unit and
its profile are evidenced. A separate isolated analog-input/converter path is equally valid when
required by the instrument or installation.

The previously discussed Rheonik/RHE08-class 4–20 mA path remains a hardware candidate/reference,
not a production-confirmed profile. RFX-00 assigns no register, scale, electrical range or Modbus
semantics to an unevidenced model.

Each accepted 4–20 mA signal requires versioned scaling/calibration metadata sufficient to map
raw acquisition to engineering value. At minimum the future implementation must represent raw
input domain, engineering range/unit, scaling policy, calibration state/version and acquisition
profile provenance. Invalid/under-range/over-range behavior must fail closed according to the
accepted hardware profile rather than be guessed generically.

### 7. Pressure reference semantics

Pressure instruments explicitly declare their pressure reference as `absolute` or `gauge`.
Refrigerant-property calculations always consume **absolute pressure**.

For a gauge-referenced pressure signal:

```text
P_absolute = P_gauge + P_atmospheric
```

`P_gauge` and `P_atmospheric` must be expressed in compatible absolute engineering units before
addition. Unit conversion is deterministic and explicit; values with incompatible or unknown
units are unavailable for calculation.

An absolute-pressure instrument bypasses gauge conversion. The calculation pipeline must never
add atmospheric pressure twice.

Atmospheric pressure is a first-class environmental/reference signal for any gauge-pressure
calculation. A fixed standard-atmosphere constant may be exposed only as an explicitly selected
simulation/manual-reference mode in a future scoped decision; it must never silently masquerade
as a measured current atmospheric value.

When a circuit requires atmospheric reference and that signal is missing, stale, invalid or of
insufficient calibration quality, dependent absolute pressure and thermodynamic metrics become
`degraded` or `unavailable` according to the calculation policy. The UI/API must expose that
reason instead of presenting a normal-looking value.

### 8. Refrigerant profile and local property provider

Each Refrigeration Circuit references one explicit, versioned **Refrigerant Profile**. The profile
identifies the refrigerant/fluid and the property-provider data/version used to evaluate saturation
properties. Unsupported or ambiguous refrigerants fail closed.

The mandatory property provider is local/offline-capable and deterministic for a pinned data or
library version. RFX-00 does not select a concrete package. A follow-up dependency-evaluation Work
Package must verify license, supported refrigerants, CPU/memory footprint, ARM64 support, offline
packaging, numerical domain, update/rollback behavior and regression fixtures before adoption.

Cloud refrigerant-property APIs may be evaluated only as optional isolated integrations and can
never be the authoritative or mandatory calculation path for `LOCAL_LAN`.

The provider contract must support the saturation semantics required for pure refrigerants and
blends. For zeotropic blends it must distinguish dew and bubble states rather than expose one
ambiguous generic saturation temperature.

### 9. Derived thermodynamic metrics

Derived metrics are deterministic read-model values calculated from accepted physical signals and
versioned circuit configuration. They do not replace raw telemetry and must retain input
provenance.

For the low side:

```text
P_low_abs = absolute_pressure(suction_pressure, atmospheric_pressure when required)
T_evap_sat = refrigerant.saturation_temperature(P_low_abs, phase=dew/evaporation)
superheat = T_suction_line - T_evap_sat
```

For the high side:

```text
P_high_abs = absolute_pressure(condensing_pressure, atmospheric_pressure when required)
T_cond_sat = refrigerant.saturation_temperature(P_high_abs, phase=bubble/condensation)
subcooling = T_cond_sat - T_liquid_line
```

For pure refrigerants, dew and bubble saturation temperature may coincide according to the
selected property provider. The API/domain contract still names the intended phase semantics so a
future blend cannot be calculated with an ambiguous generic saturation call.

Canonical derived metrics include at least:

- `refrigeration.temperature.evaporation_saturation` in `degC`;
- `refrigeration.temperature.condensation_saturation` in `degC`;
- `refrigeration.superheat` in kelvin temperature difference (`K`);
- `refrigeration.subcooling` in kelvin temperature difference (`K`).

Temperature differences are stored/exposed as `K`, not as an absolute temperature unit. UI may
format a temperature difference with an operator-friendly label, but the typed API/domain unit
must remain unambiguous.

A future implementation may materialize derived results for efficient history/reporting or
calculate them on demand from persisted raw inputs. That storage choice must not change the
formula, provenance or quality contract defined here.

### 10. Timestamp, freshness and quality propagation

Every calculation is evaluated at an explicit `observation_at` timestamp and against a versioned
calculation policy. `observation_at` is part of the persisted result/provenance contract: it is the
time against which sample age and future-clock-skew validity were evaluated, and it is distinct from
both source sample time and calculation execution time.

For each uniquely resolved semantic binding, source-sample selection is deterministic and occurs
before quality/freshness gates. Candidate samples are first restricted to the resolved binding's
half-open validity interval: `valid_from <= captured_at < valid_to`, or
`valid_from <= captured_at` when `valid_to = null`. A sample captured before the role assignment
started or after it ended can never satisfy that role, even if it is otherwise fresh.

Within that binding-valid candidate set:

1. prefer samples with `captured_at <= observation_at` and select the greatest
   `(captured_at, event_id)` tuple, using canonical `event_id` descending as the equal-timestamp
   tie-breaker;
2. a slightly future-dated sample never outranks any sample at or before `observation_at`;
3. only when no binding-valid sample exists at or before `observation_at` may a calculation policy
   explicitly allow a future candidate, in which case select the smallest
   `captured_at > observation_at` (nearest future sample) that is still inside the same binding
   validity interval, and use canonical `event_id` descending for equal timestamps;
4. the selected candidate then passes the normal quality, maximum-age, future-clock-skew and
   cross-input-skew gates. A future candidate outside the configured tolerance is `unavailable`.

This selection algorithm is part of the versioned calculation policy. Implementations must not use
arrival order, database physical order or UI refresh timing as an implicit tie-breaker. Inputs do not
need identical timestamps, but every selected required input must satisfy the policy's maximum age,
cross-input skew and maximum future-clock-skew limits. Those limits are domain configuration and must
not be silently borrowed from frontend polling intervals.

Maximum-age and future-clock-skew are separate gates with exact boundary semantics. For each selected
source sample define:

```text
sample_age = max(0, observation_at - captured_at)
future_offset = max(0, captured_at - observation_at)
```

A non-future or exactly-at-observation sample passes the maximum-age gate when
`sample_age <= maximum_age`; equality at the configured maximum is accepted. A future sample has
`sample_age = 0` for this gate and is not evaluated with absolute age. It must independently satisfy
`0 < future_offset <= maximum_future_clock_skew`; equality at the configured future-skew maximum is
accepted, while any larger future offset makes the result `unavailable`. A policy that does not
explicitly allow future candidates has an effective `maximum_future_clock_skew = 0` and therefore
rejects them. This separation prevents signed-age or absolute-age interpretations from changing
availability.

Cross-input skew is evaluated **per derived metric dependency set**, not across every signal selected
for the refrigeration circuit. For one derived metric instance, take the transitive set of physical
source samples required by that metric after pressure-reference expansion (for example atmospheric
pressure when a gauge-pressure source is used), then compute:

```text
cross_input_skew = max(required_source.captured_at) - min(required_source.captured_at)
```

Unrelated circuit measurements and inputs used only by other derived metrics are excluded. The
metric becomes `unavailable` when this dependency-set skew exceeds its versioned calculation-policy
limit.

Derived availability uses three presentation states:

- `available` — every required input is acceptable and the property query is inside its validated
  domain;
- `degraded` — a value is intentionally permitted by an explicit accepted policy while one or more
  non-fatal input/provenance limitations must be shown to the operator;
- `unavailable` — no trustworthy value may be emitted.

The default/fail-safe rule is `unavailable`. A future Work Package may define narrowly permitted
`degraded` cases; the implementation must not invent them ad hoc.

A derived result can never have a newer effective timestamp, better freshness or better quality
than its least-trustworthy required input. The derived contract therefore separates
`effective_at` from `computed_at`. For any `available` or `degraded` numeric result with a complete
required physical-source dependency set, `effective_at` is exactly:

```text
effective_at = min(observation_at, min(required_source.captured_at))
```

`computed_at` records when NEXOLAB performed the calculation. A source timestamp that is slightly
future-dated but still inside the explicitly accepted future-clock-skew tolerance remains preserved
in provenance; it does not move `effective_at` later than `observation_at`. Recalculation alone can
never make stale or future-dated physical evidence appear fresh. An `unavailable` result with an
incomplete required-source set carries `effective_at = null`; if all required sources are present but
a later quality/domain gate rejects them, the same exact formula is retained for diagnostic
provenance. Provenance records `observation_at`, `computed_at`, `effective_at` and every source sample
timestamp so historical/backfilled availability decisions are reproducible.

At minimum the calculation pipeline must reject or explicitly classify:

- missing required binding or sample;
- canonical telemetry `sensor_error`, `communication_error` or `unknown` quality;
- stale sample, excessive cross-input timestamp skew or excessive future-clock skew;
- instrument or acquisition profile that was not accepted at `observation_at` (historical/backfill
  resolves the acceptance state at that historical `observation_at`, never the current wall-clock
  state). Instrument and acquisition-profile acceptance histories use non-overlapping half-open
  `[effective_from, effective_to)` intervals. At an activation/deactivation timestamp, the state whose
  `effective_from` equals that timestamp is the post-transition state and is effective immediately;
  the previous state is not. Same-timestamp state-change operations are serialized by a monotonic
  revision sequence, and only the final revision may own a non-empty interval beginning at that
  timestamp; intermediate same-timestamp revisions are zero-width audit records. Any remaining
  overlapping/non-unique effective state fails closed as `unavailable`;
- missing/expired/unacceptable calibration state where the metric policy requires calibration;
- unknown engineering unit or pressure reference;
- missing atmospheric reference for gauge pressure;
- unsupported refrigerant/profile version;
- pressure outside the validated refrigerant-property domain;
- non-finite property-provider result.

Raw telemetry remains authoritative evidence. Derived-quality state is additional calculation
metadata and does not rewrite raw event quality.

### 11. Provenance

Every derived value must be explainable. The calculation result/provenance contract must retain or
resolve at least:

- circuit/configuration version;
- calculation-policy version;
- refrigerant-profile and property-provider data/library version;
- derived metric identifier and formula version;
- `observation_at`, `effective_at` and `computed_at`;
- each required signal/binding identity and binding validity interval;
- source telemetry event identity and `captured_at` for each physical input;
- the instrument identity/version, acquisition/scaling-profile version and calibration
  record/version that were effective at each selected source sample's `captured_at` and therefore
  produced/interpreted that persisted engineering value;
- instrument lifecycle/acceptance state resolved at `observation_at`;
- acquisition/scaling-profile acceptance state resolved at `observation_at`;
- calibration state/validity resolved both at the selected sample's `captured_at` and at
  `observation_at` when the metric policy requires current calibration acceptance;
- pressure-reference conversion applied, including atmospheric source when used;
- input units and deterministic conversions;
- resulting availability/quality state and reason codes.

Those quality-gate references must resolve immutable historical metadata or be snapshotted in the
result provenance. Production-time metadata and observation-time acceptance are separate facts: a
later calibration renewal or profile change must not be attributed to a sample that was produced
under an older version, and a later instrument lifecycle transition must not retroactively change
why a historical derived result was accepted or rejected. Instrument and acquisition-profile
acceptance at `observation_at` are mandatory gates for every derived calculation. Calibration has the
additional versioned metric-policy rule described above; whenever that policy requires calibration,
any required production-time or observation-time calibration gate failing makes the result
`unavailable`.

A report/export must be able to trace a derived value back to this provenance without querying a
cloud service or reconstructing meaning from UI labels.

### 12. Persistence and read-model boundaries

PostgreSQL remains the central system of record. Existing telemetry tables continue to persist
normalized physical samples; no device-specific telemetry table is introduced by this decision.

Future refrigeration persistence should separate relatively slow-changing configuration from
high-volume observations:

- instrumentation/acquisition profile and calibration metadata;
- semantic signal bindings and their validity intervals;
- refrigeration circuits and refrigerant/configuration versions;
- optional persisted derived-result/provenance records or deterministic calculation snapshots.

The structural snapshot remains a bounded equipment/read-model endpoint. It may later expose
process instrumentation and derived summaries, but it must not become a history scan or trigger
physical polling. History/calculation APIs remain read-only consumers of persisted telemetry and
configuration.

Any migration must preserve organization scoping, immutable historical evidence where already
promised, optimistic-concurrency/version semantics and existing backup/restore boundaries.

### 13. Compatibility with current refrigeration contracts

The current refrigeration implementation is retained and extended rather than replaced wholesale:

- `refrigeration_equipment` remains the existing refrigeration Asset/passport/lifecycle record;
- `measurement_devices` and `measurement_channels` remain useful acquisition/channel catalog
  primitives, but their current temperature/energy assumptions are not sufficient as universal
  instrumentation semantics;
- `physical_sensors` remain valid metrological inventory for the current climate-temperature
  catalog and may inform the generalized Instrument model after a focused migration decision;
- canonical telemetry `node_id/equipment_id/channel_id/metric/unit/quality/captured_at` remains the
  physical observation envelope;
- `refrigeration_sensor_bindings` remain the current cabinet/product-temperature placement model;
  future semantic circuit bindings must not overload `side/shelf/position` fields;
- refrigeration layout drafts/revisions/images remain presentation/layout state and do not own
  process measurement semantics;
- sensor configuration continues to validate current climate-chamber channels while generalized
  process instrumentation is introduced through a focused compatible API/migration;
- the structural snapshot continues to expose configured channels even when telemetry is absent,
  with missing data explicit rather than triggering acquisition.

Compatibility adapters may project new generalized instruments/signals into existing refrigeration
UI contracts during migration. The adapter must be one-way/read-model compatibility where
possible; new canonical process semantics must not be encoded back into legacy labels or slot
positions.

No existing production row is renamed or backfilled in RFX-00. Migration design and rollout are
separate implementation Work Packages with explicit downgrade/rollback and data-preservation tests.

### 14. Safety and runtime boundary

This architecture is monitoring-only.

- No Modbus write command is added or permitted.
- No controller setpoint, relay, address or configuration write is required for derived metrics.
- Hardware/profile discovery remains read-only and evidence-gated.
- Hardware acceptance requires real-device evidence and is never inferred from software tests.
- Core acquisition, persistence, calculation and local UI must work without internet.
- No paid runtime service is permitted.
- Optional online integrations cannot become a dependency of calculation availability.
- Stale, missing or invalid measurements must never be silently displayed as current valid values.

## Rejected alternatives

### Infer process meaning from controller/channel names

Rejected. Controller identity describes acquisition, not whether a channel is suction pressure,
humidity or liquid-line temperature. Labels are mutable presentation data and are not safe
calculation contracts.

### Store pressure only as gauge and let each UI convert it

Rejected. Absolute-pressure conversion is part of the deterministic domain calculation and must
use explicit pressure-reference provenance. Duplicating conversion in clients risks inconsistent
results and accidental double atmospheric compensation.

### Use one generic saturation-temperature function without phase semantics

Rejected. It is ambiguous for zeotropic blends and can produce incorrect superheat/subcooling
semantics. Dew/evaporation and bubble/condensation intent remains explicit even when a pure fluid
returns the same saturation temperature for both.

### Make a cloud refrigerant-property API authoritative

Rejected. `LOCAL_LAN` core runtime must work disconnected and without paid services. A local,
pinned provider is mandatory; any cloud adapter is optional only.

### Persist only derived values and discard source linkage

Rejected. Laboratory/industrial results must be explainable and reproducible. Raw telemetry and
configuration provenance remain authoritative evidence.

## Consequences

### Positive

- acquisition hardware can evolve without changing refrigeration process semantics;
- temperature, humidity and pressure are explicitly typed rather than inferred from device family;
- gauge/absolute pressure conversion becomes deterministic and auditable;
- refrigerant-aware calculations work consistently across UI, reports and future analytics;
- zeotropic blends have correct dew/bubble semantics from the start;
- derived metrics cannot silently outrank the quality/freshness of their inputs;
- current refrigeration layouts and temperature placement can remain operational during migration;
- the mandatory calculation path remains offline and vendor/cloud independent.

### Costs and risks

- generalized instrumentation/circuit persistence requires a focused migration rather than reusing
  the existing placement table for every concept;
- property-provider selection needs numerical, licensing, ARM64 and offline-package evaluation;
- real 4–20 mA/XJP60D/converter capability remains hardware-unverified until physical evidence is
  collected;
- calculation freshness/skew/calibration policy must be explicitly defined before production
  results are exposed;
- historical semantic binding/versioning adds configuration complexity but is required for
  reproducible evidence.

## Follow-up Work Package decomposition

RFX-00 intentionally stops at architecture. Implementation proceeds as focused vertical slices in
this dependency order.

1. **RFX-01 — Instrumentation and semantic-binding domain/persistence**
   - introduce generalized Instrument, Signal and semantic Binding contracts;
   - preserve current refrigeration placement/layout behavior through compatibility adapters;
   - add migrations, organization isolation, audit/version history and rollback tests;
   - no Device Agent or hardware behavior change.

2. **RFX-02 — 4–20 mA acquisition profile contract and hardware inventory**
   - define machine-readable analog scaling/profile schema and read-only acquisition boundary;
   - identify exact XJP60D analog hardware and any isolated converter candidates;
   - add recorded-frame/profile tests only for evidence-backed behavior;
   - keep unevidenced hardware explicitly `hardware unverified`.

3. **RFX-03 — Refrigeration circuit and refrigerant configuration**
   - persist circuit identity, semantic role bindings and refrigerant/profile version;
   - implement configuration validation and historical validity;
   - no property calculation until the provider boundary is accepted.

4. **RFX-04 — Offline refrigerant-property provider evaluation**
   - select/pin a local provider after license, numerical-domain, ARM64, CPU/RAM and offline-bundle
     acceptance;
   - create golden saturation fixtures including pure-fluid and blend dew/bubble cases;
   - prove unsupported refrigerants/domain errors fail closed.

5. **RFX-05 — Derived thermodynamics engine and provenance**
   - implement absolute-pressure normalization, saturation temperatures, superheat and subcooling;
   - implement freshness/skew/quality/calibration propagation and deterministic reason codes;
   - preserve source-event and configuration provenance.

6. **RFX-06 — Refrigeration monitoring API/read models and operator UI**
   - expose typed physical/derived values with quality/provenance summaries;
   - extend bounded structural/read models without history scans or acquisition side effects;
   - add circuit/instrument configuration UI with explicit unavailable/degraded states;
   - preserve icon/low-noise NEXOLAB interaction patterns without hiding critical quality text.

7. **RFX-07 — Controlled hardware/runtime acceptance**
   - verify exact humidity, pressure, atmospheric-reference and analog acquisition hardware;
   - verify calibration/scaling against physical references where available;
   - verify real circuit calculations against independent expected values;
   - classify software verified vs hardware verified explicitly;
   - any physical change/cutover requires the normal separate approval boundary.

Each Work Package maps to one Issue, branch and focused PR. Hardware acceptance does not block
software-only domain/provider work when the required physical semantics are represented as
unverified and fail closed.

## Verification for this decision

RFX-00 acceptance requires only repository/documentation evidence:

- ADR identifier/registry integrity;
- reconciliation against current refrigeration equipment, sensor binding, climate catalog,
  structural snapshot and telemetry contracts;
- project-state integrity;
- formatting and `git diff --check`;
- exact-head repository CI and NEXOLAB Merge Gate.

No software test, mock or ADR can satisfy RFX-02/RFX-07 real-hardware acceptance. Those boundaries
remain explicitly unverified until physical evidence is collected.
