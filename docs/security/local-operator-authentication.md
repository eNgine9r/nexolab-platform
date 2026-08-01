# Local operator authentication

This runbook configures fail-closed operator login for the `LOCAL_LAN` profile. It does not authorize production/site cutover by itself.

## Security boundary

Local authentication requires all of the following:

- PostgreSQL migrations at the current head;
- `AUTH_MODE=jwt`;
- `AUTH_LOCAL_ENABLED=true`;
- a matching operator-owned RSA private/public key pair;
- at least one bootstrapped local account with an active organization membership;
- dashboard built with `NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=local`.

Telemetry Service exits during startup if local authentication is enabled and the signing-key files are missing, malformed, too small or mismatched. It never falls back to `AUTH_MODE=disabled` or to a remote JWKS provider.

## Files and permissions

Create a host directory that is not inside Git-tracked source:

```bash
install -d -m 0700 ./secrets/local-auth
```

Generate the key pair with the Telemetry Service image or a local Python environment containing its dependencies:

```bash
cd infrastructure/compose

docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  run --rm --no-deps \
  -v "$PWD/secrets/local-auth:/operator-secrets" \
  telemetry-service \
  python -m app.security.local_cli generate-keys \
  --private-key-file /operator-secrets/private.pem \
  --public-key-file /operator-secrets/public.pem
```

Expected host permissions:

```text
private.pem 0600
public.pem  0644
parent directory 0700
```

Do not copy either file into an image. Do not commit either file. The private key must be backed up through the controlled secret-backup process separately from PostgreSQL.

## Environment

Copy `.env.central.example` to the operator-owned `.env.central` and set absolute or compose-directory-relative host paths:

```dotenv
AUTH_MODE=disabled
AUTH_LOCAL_PRIVATE_KEY_HOST_FILE=./secrets/local-auth/private.pem
AUTH_LOCAL_PUBLIC_KEY_HOST_FILE=./secrets/local-auth/public.pem
AUTH_LOCAL_ISSUER=urn:nexolab:local
AUTH_LOCAL_AUDIENCE=nexolab-api
AUTH_LOCAL_ACCESS_TOKEN_SECONDS=300
AUTH_LOCAL_REFRESH_TOKEN_SECONDS=43200
AUTH_LOCAL_MAX_FAILED_ATTEMPTS=5
AUTH_LOCAL_LOCKOUT_SECONDS=300
```

`compose.local-auth.yaml` overrides the container to `AUTH_MODE=jwt` and `AUTH_LOCAL_ENABLED=true`. Keeping `AUTH_MODE=disabled` in the shared environment prevents accidental activation when the required overlay is omitted; the production start command must include the overlay.

Validate the merged configuration without printing secret contents:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  -f compose.local-auth.yaml \
  config --quiet
```

## Database migration

Apply the current migration head before bootstrap:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  -f compose.local-auth.yaml \
  run --rm telemetry-migrate
```

The local-auth tables are:

```text
security_local_accounts
security_local_sessions
```

Identities, memberships, roles and audit records remain in the existing security tables.

## First administrator bootstrap

Create a temporary password file outside Git. The command rejects passwords shorter than 12 characters and removes no existing account:

```bash
install -m 0600 /dev/null /tmp/nexolab-admin-password
read -r -s -p 'Initial administrator password: ' PASSWORD
printf '%s' "$PASSWORD" > /tmp/nexolab-admin-password
unset PASSWORD
```

Run the explicit bootstrap command:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  -f compose.local-auth.yaml \
  run --rm --no-deps \
  -v /tmp/nexolab-admin-password:/run/operator-password:ro \
  telemetry-service \
  python -m app.security.local_cli bootstrap-admin \
  --username administrator \
  --password-file /run/operator-password \
  --display-name 'NEXOLAB Administrator' \
  --organization-id 00000000-0000-0000-0000-000000000001 \
  --organization-slug nexolab-lab \
  --organization-name 'NEXOLAB Laboratory'
```

Delete the temporary file immediately:

```bash
shred -u /tmp/nexolab-admin-password 2>/dev/null || rm -f /tmp/nexolab-admin-password
```

The bootstrap command fails if the normalized username already exists. It never resets an existing password implicitly.

## Start

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  -f compose.local-auth.yaml \
  up -d --no-build --wait
```

For the offline bundle, also include `infrastructure/offline/compose.central.offline.yaml` and use `--pull never` as documented in `docs/operations/offline-installation.md`.

## Login and session behavior

- access token lifetime defaults to 5 minutes;
- refresh session lifetime defaults to 12 hours;
- refresh tokens rotate on every refresh;
- reuse of a rotated token is rejected;
- logout revokes the PostgreSQL session;
- access tokens from a revoked session are rejected immediately;
- five failed password attempts lock the account for five minutes by default;
- passwords and refresh tokens are never written to audit snapshots;
- organization and role authorization remain server-side.

## Password recovery

Create a new temporary password file using the same procedure as bootstrap, then run:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  -f compose.local-auth.yaml \
  run --rm --no-deps \
  -v /tmp/nexolab-new-password:/run/operator-password:ro \
  telemetry-service \
  python -m app.security.local_cli reset-password \
  --username administrator \
  --password-file /run/operator-password
```

Password reset revokes every active refresh session for that account. Existing access JWTs are rejected through their revoked `sid`.

## Emergency session revocation

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  -f compose.local-auth.yaml \
  run --rm --no-deps telemetry-service \
  python -m app.security.local_cli revoke-sessions \
  --username administrator
```

## Key rotation

Key rotation invalidates every currently issued access JWT. Perform it only in a controlled maintenance window:

1. stop the dashboard/API entry point;
2. back up PostgreSQL and the current private/public key pair;
3. generate a new pair at new paths;
4. update the two host-file variables;
5. recreate Telemetry Service with the local-auth overlay;
6. verify login and RBAC;
7. retain the old pair only for the documented rollback window, then destroy it securely.

Refresh sessions remain in PostgreSQL, but refresh produces tokens under the new key after successful validation.

## Backup and restore

Back up together:

- PostgreSQL, including all `security_*` tables;
- the local private/public signing key pair;
- the operator-owned `.env.central` without exposing it in logs or artifacts.

A database restore without the matching signing key preserves accounts but invalidates existing access tokens. A key restore without the matching database cannot restore refresh sessions or memberships.

## Rollback

Rollback must preserve PostgreSQL volumes. Never use `docker compose down -v`.

Rolling back to a version before ADR 0009 disables local login endpoints and does not understand the local session tables. Keep the database and key files intact, restore the previous explicit authentication profile, and do not claim local authentication is available until returning to an ADR-0009-capable image.

## Verification checklist

- [ ] Compose config includes `compose.local-auth.yaml`.
- [ ] Telemetry Service fails when either key file is absent.
- [ ] A valid local operator can log in while internet egress is blocked.
- [ ] Viewer, operator and administrator permissions differ as expected.
- [ ] Logout causes the previous access token to return HTTP 401.
- [ ] Rotated refresh-token replay returns HTTP 401.
- [ ] Audit records identify provider `nexolab-local` and the local actor subject.
- [ ] PostgreSQL and signing keys are present in the controlled backup set.
- [ ] No password, token or private key appears in Git, logs or artifacts.
