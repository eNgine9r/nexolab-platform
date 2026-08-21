# LOCAL_LAN equipment discovery architecture

Issue: #606

Profile: `LOCAL_LAN`

## Purpose

NEXOLAB discovery finds previously unknown Ethernet/IP equipment only inside explicitly approved private laboratory subnets. Discovery produces persisted evidence for operator review; it never enrolls a device into acquisition automatically.

The domain lives inside `telemetry-service` so persistence, organization scoping, RBAC and immutable security audit reuse existing local infrastructure. The service remains on the normal Compose bridge network; no host networking, privileged container, raw socket, Docker socket or external inventory service is required.

## Discovery safety boundary

Discovery is fail-closed. `EQUIPMENT_DISCOVERY_ALLOWED_CIDRS` must contain explicit RFC1918 IPv4 scopes before scanning is enabled. Requested CIDRs must be subnets of that allowlist, requested ports must be contained in the configured port allowlist, and host/port/concurrency/timeout budgets are bounded before a scan row is created. Manual scan requests must provide non-empty CIDR and port lists explicitly; only the internal scheduled path may resolve the configured defaults.

The scanner performs TCP connection establishment only. It sends zero application payload bytes, performs no authentication attempt and does not issue Modbus, HTTP, MQTT or vendor-protocol commands. Port `502` is only TCP-connect evidence and is not a Modbus identity/read/write adapter.

Cancellation is checked between bounded host batches. Scheduled scans are disabled by default and, when explicitly enabled, have a minimum interval of five minutes and use only the configured allowlist scope.

## Persisted evidence and tenant isolation

Each scan stores its requested scope, budgets, completion metrics and result counts. Candidates preserve first/last seen state and lifecycle, while each scan observation is immutable and retains the observed network/service evidence plus a deterministic fingerprint. Candidate identity is the observed IP endpoint (`ip:<address>`); MAC addresses remain evidence rather than identity because proxy ARP and multi-address devices may legitimately expose the same MAC for multiple IP endpoints.

Change detection compares fingerprints only against the most recent observation from the same deterministic scan scope (CIDR set plus requested TCP-port set). Partial-port rescans therefore cannot manufacture a change event by omitting untested services. Neighbor-only evidence is not treated as permanently present: if a later covering scan sees neither the neighbor entry nor an open requested service, the candidate is marked disappeared.

The discovery overview exposes bounded candidate pagination and a total count so every persisted candidate remains reachable even when a scan produces more than one UI page. The frontend renders one server-side page at a time and rejects obsolete responses when the active organization/repository changes.

Database ownership is organization-scoped. Candidate-to-scan, observation-to-scan, observation-to-candidate and adopted network-asset-to-candidate relationships enforce matching `organization_id` values at the database layer. A partial PostgreSQL unique index allows at most one running scan per organization.

## Operator workflow

The Equipment workspace follows:

`discover candidate → inspect evidence → review/match/ignore/adopt → administrative network identity`

Read access uses the existing dashboard permission. Starting/cancelling scans and candidate actions require `equipment.manage`, use optimistic `If-Match` versions and append security audit events. Local match suggestions are presentation-only hints derived from already loaded canonical Equipment registry tokens and never auto-link a candidate.

Adoption creates only an `equipment_network_assets` administrative identity. It does not create a measurement device, enable an acquisition target, alter Device Agent state, change RS-485 ownership, change polling cadence or write to hardware.

## Runtime and offline properties

Mandatory behavior uses only local PostgreSQL, local authentication/authorization and LOCAL_LAN connectivity. No cloud OUI lookup, external vendor API, CDN, telemetry service or paid runtime dependency is required. The Compose defaults keep discovery disabled until an operator-controlled CIDR allowlist is configured.

## Verification boundary

Software verification covers policy enforcement, zero-payload scanner behavior, cancellation, scheduling limits, candidate diff/lifecycle persistence, RBAC, auditing, optimistic candidate actions, schema/migration integrity and route-mocked browser behavior.

Real Raspberry Pi/LAN acceptance remains a separate hardware/runtime evidence gate. No real network scan, Modbus operation, acquisition mutation, hardware write or production/site cutover is authorized merely by this implementation.
