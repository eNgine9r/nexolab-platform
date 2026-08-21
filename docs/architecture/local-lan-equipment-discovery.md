# LOCAL_LAN equipment discovery architecture

Issue: #606

Profile: `LOCAL_LAN`

## Purpose

NEXOLAB discovery finds previously unknown Ethernet/IP equipment only inside explicitly approved private laboratory subnets. Discovery produces persisted evidence for operator review; it never enrolls a device into acquisition automatically.

The domain lives inside `telemetry-service` so persistence, organization scoping, RBAC and immutable security audit reuse existing local infrastructure. The service remains on the normal Compose bridge network; no host networking, privileged container, raw socket, Docker socket or external inventory service is required.

## Discovery safety boundary

Discovery is fail-closed. `EQUIPMENT_DISCOVERY_ALLOWED_CIDRS` must contain explicit RFC1918 IPv4 scopes before scanning is enabled. Requested CIDRs must be subnets of that allowlist, requested ports must be contained in the configured port allowlist, and host/port/concurrency/timeout budgets are bounded before a scan row is created. Manual scan requests must provide non-empty CIDR and port lists explicitly; only the internal scheduled path may resolve the configured defaults.

The production scanner performs TCP connection establishment only. It sends zero application payload bytes, performs no authentication attempt and does not issue Modbus, HTTP, MQTT or vendor-protocol commands. Port `502` is only TCP-connect evidence and is not a Modbus identity/read/write adapter.

The telemetry container runs in the normal Compose bridge network, so container `/proc/net/arp` is not treated as authoritative physical-LAN evidence. Production discovery therefore does not read it by default and does not claim MAC/interface evidence from the container namespace. The scanner can consume a separately supplied read-only neighbor snapshot only when a future adapter can prove that source belongs to the intended LAN namespace; no such host-side adapter is enabled by this Work Package. This preserves the no-host-networking/no-privileged-runtime boundary instead of presenting bridge ARP data as real equipment evidence.

Cancellation is checked between bounded host batches. Partial network-activity metrics from completed batches are persisted when a scan is cancelled. Scheduled scans are disabled by default and, when explicitly enabled, have a minimum interval of five minutes and use only the configured allowlist scope.

## Persisted evidence and tenant isolation

Each scan stores its requested scope, budgets, completion metrics and result counts. Candidates preserve first/last seen state and lifecycle, while each scan observation is immutable and retains the observed network/service evidence plus a deterministic fingerprint. Candidate identity is the observed IP endpoint (`ip:<address>`); MAC addresses, when supplied by an explicitly authoritative neighbor source, remain evidence rather than identity because proxy ARP and multi-address devices may legitimately expose the same MAC for multiple IP endpoints.

Change detection compares fingerprints only against the most recent observation from the same deterministic scan scope (CIDR set plus requested TCP-port set). Partial-port rescans therefore cannot manufacture a change event by omitting untested services. If explicit neighbor evidence is available for a candidate, it is not treated as permanently present: a later covering scan with the same evidence capability can mark the candidate disappeared when neither neighbor evidence nor an open requested service remains.

The discovery overview exposes bounded candidate pagination and a total count so every persisted candidate remains reachable even when a scan produces more than one UI page. The frontend renders one server-side page at a time and rejects obsolete responses when the active organization/repository changes.

Database ownership is organization-scoped. Candidate-to-scan, observation-to-scan, observation-to-candidate and adopted network-asset-to-candidate relationships enforce matching `organization_id` values at the database layer. A partial PostgreSQL unique index allows at most one running scan per organization. Finalization retries are restricted to transient connectivity/transaction failures; permanent database errors are surfaced into the failed-scan path instead of being retried indefinitely.

## Operator workflow

The Equipment workspace follows:

`discover candidate → inspect evidence → review/match/ignore/adopt → administrative network identity`

Read access uses the existing dashboard permission. Starting/cancelling scans and candidate actions require `equipment.manage`, use optimistic `If-Match` versions and append security audit events. Local match suggestions are presentation-only hints derived from already loaded canonical Equipment registry tokens and never auto-link a candidate.

Adoption creates only an `equipment_network_assets` administrative identity. It does not create a measurement device, enable an acquisition target, alter Device Agent state, change RS-485 ownership, change polling cadence or write to hardware.

## Runtime and offline properties

Mandatory behavior uses only local PostgreSQL, local authentication/authorization and LOCAL_LAN connectivity. No cloud OUI lookup, external vendor API, CDN, telemetry service or paid runtime dependency is required. The Compose defaults keep discovery disabled until an operator-controlled CIDR allowlist is configured.

## Verification boundary

Software verification covers policy enforcement, zero-payload scanner behavior, cancellation and partial-metric persistence, transient-only database retry behavior, scheduling limits, candidate diff/lifecycle persistence, RBAC, auditing, optimistic candidate actions, schema/migration integrity and route-mocked browser behavior.

Real Raspberry Pi/LAN acceptance remains a separate hardware/runtime evidence gate. No real network scan, Modbus operation, acquisition mutation, hardware write or production/site cutover is authorized merely by this implementation.
