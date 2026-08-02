# ADR 0009 — Local operator authentication for disconnected laboratories

- Status: Accepted
- Date: 2026-08-01
- Decision owners: Product Owner, NEXOLAB engineering
- Profile: `LOCAL_LAN`

## Context

NEXOLAB must continue operating when the laboratory LAN has no internet access. The existing security boundary already verifies JWT signatures, maps provider subjects to local identities, resolves organization memberships, enforces server-side RBAC and records immutable audit attribution. However, the only implemented interactive browser adapter was optional Supabase Auth, while `AUTH_MODE=disabled` was limited to development and controlled acceptance.

Making Supabase, Keycloak, another OIDC appliance or a cloud JWKS endpoint mandatory would add a new runtime dependency and would either require internet access or introduce another independently operated service into the minimum deployment. Leaving authentication disabled would violate the fail-closed production boundary.

## Decision

Telemetry Service is the local identity authority for the `LOCAL_LAN` profile.

The implementation reuses the existing provider-neutral security model instead of creating a parallel authorization system:

- local identities use provider `nexolab-local`;
- accounts are stored in PostgreSQL and point to existing `security_identities` rows;
- organization memberships and roles remain in existing security tables;
- passwords are stored only as salted `scrypt` hashes;
- access tokens are short-lived RS256 JWTs;
- the private signing key and matching public key are operator-owned files mounted at runtime;
- refresh tokens are random opaque values; only SHA-256 hashes are persisted;
- every access JWT contains a local session identifier (`sid`);
- authenticated requests validate both the JWT and the current PostgreSQL session state;
- logout, password reset or explicit revocation invalidates access immediately through the `sid` check;
- repeated password failures trigger a bounded database-backed lockout;
- login success is attributed to the authenticated local actor in immutable audit records;
- first-account bootstrap and recovery are explicit CLI operations that read passwords from an external file;
- no password, private key, refresh token or production identity data is included in source, images or offline bundles.

`AUTH_MODE=disabled` remains available only for development and isolated validation. Optional external JWT/Supabase/OIDC providers remain supported but are not part of the mandatory offline runtime.

## Consequences

### Positive

- operator login, refresh, logout and RBAC work without internet;
- no additional mandatory container or paid service is introduced;
- existing organization isolation, permissions and audit contracts remain authoritative;
- accounts and sessions are included in normal PostgreSQL backup and recovery;
- revocation does not wait for access-token expiry;
- key rotation and password recovery are explicit operational procedures.

### Costs and risks

- Telemetry Service now owns credential verification and token issuance for the local profile;
- the private signing key becomes critical host secret material and must be backed up separately from the database;
- browser refresh tokens are retained only in tab-scoped `sessionStorage`, so browser XSS defenses remain important;
- database availability is required for local token validation and revocation;
- multi-host active-active local token issuance is not supported until signing-key distribution and coordinated operations are designed.

## Rejected alternatives

### Mandatory Supabase or another cloud identity service

Rejected because core runtime and operator login must remain available without internet or paid services.

### Mandatory Keycloak or another standalone identity appliance

Rejected for the current minimum deployment because it adds another stateful service, backup surface, update path and offline artifact. It may be reconsidered if federated multi-site identity becomes a product requirement.

### Long-lived static bearer token

Rejected because it has no safe interactive password flow, bounded session lifecycle, per-user attribution or practical revocation.

### Production use of `AUTH_MODE=disabled`

Rejected because it grants administrator authority without verified identity and cannot satisfy fail-closed operation or audit attribution.

### Browser-supplied roles

Rejected. Roles and permissions remain server-side membership data and are never trusted from JWT custom claims or browser storage.

## Verification

The decision is accepted only with evidence for:

- migration upgrade and downgrade consistency;
- password hashing and malformed-hash rejection;
- missing or mismatched key startup failure;
- login, refresh rotation, logout and post-revocation access rejection;
- viewer, operator and administrator server-side permissions;
- immutable local actor attribution;
- disconnected browser acceptance with container egress blocked;
- update and rollback preservation of PostgreSQL account/session data;
- absence of secret material in Git and the offline bundle.
