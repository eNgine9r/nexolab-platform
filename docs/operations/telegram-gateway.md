# Telegram gateway

The NEXOLAB Telegram gateway is an **optional online delivery adapter** for persisted
refrigeration morning-report snapshots. PostgreSQL, telemetry acquisition, TG-01 report
generation and the LOCAL_LAN dashboard remain authoritative and continue without it.

Initial acceptance target: Telegram group `Тест лаб`. The group title is human evidence
only; delivery uses an explicit negative group/supergroup chat ID supplied through runtime configuration.

## Safety boundary

- outbound Telegram Bot API HTTPS only;
- no public Bot API webhook or inbound Raspberry Pi port;
- no Device Agent or Modbus access;
- no controller, relay, compressor or hardware write path;
- no bot token, backend password or bearer token in Git, logs or evidence;
- persisted TG-01 snapshots are read through the authenticated NEXOLAB API;
- Telegram failure cannot block local report generation.

TG-02 proves software behavior with mocks. BotFather setup, real group membership,
secret provisioning, real send acceptance and production cutover belong to TG-04 / #825.

## Runtime composition

Use `infrastructure/compose/compose.telegram.yaml` only as an overlay to the central
Compose definition. The service is behind the explicit `telegram` profile and defaults
to `TELEGRAM_ENABLED=false`, so adding the overlay does not make Telegram mandatory.

The gateway mounts `/etc/nexolab/telegram` read-only at `/run/secrets/telegram` and
persists delivery state in the `telegram-delivery-data` named volume. Expected protected
files when TG-04 enables delivery are:

```text
/etc/nexolab/telegram/bot-token
/etc/nexolab/telegram/nexolab-backend-password
```

Do not create these files through Git, shell history, screenshots or PR comments.
Use the controlled host secret procedure during TG-04.

The recommended backend identity is a dedicated least-privilege local NEXOLAB Viewer
account. `TELEGRAM_NEXOLAB_BACKEND_ORGANIZATION_ID` must be set explicitly to the authorized
organization UUID; there is no implicit production fallback. The gateway obtains short-lived
access/refresh tokens in memory and never stores them in the outbox.

## Delivery semantics

Each logical delivery is keyed by persisted `snapshot_id + destination_chat_id`.
The local SQLite outbox records:

```text
pending → sending → sent
                  ↘ retry_wait → sending
                  ↘ failed
```

A normal restart does not resend a `sent` delivery. Timeouts, HTTP 429 and Bot API 5xx
responses use bounded retry/backoff; non-retryable 4xx failures become explicit `failed`.

Telegram Bot API does not provide an exactly-once client idempotency key for `sendMessage`.
If Telegram accepted the message but the gateway crashes before the local `sent` commit,
the result is unknowable. A stale `sending` row is recovered with `duplicate_risk=1` and
is retryable. This is an explicit residual **at-least-once** boundary, not an exactly-once
claim.

The group action is a normal URL inline button named `Відкрити NEXOLAB`. It points to the
configured Telegram Direct Link Mini App `startapp` template. Group messages never use
`InlineKeyboardButton.web_app` and the gateway sends plain text without `parse_mode`.

## Health and software verification

Disabled mode is healthy and requires no Telegram configuration. Enabled mode with
missing/invalid configuration starts in a degraded state rather than crashing core
NEXOLAB. `/health/ready` exposes only bounded operational state and never credentials.

TG-02 software verification uses local/mock endpoints only:

```bash
python -m compileall -q services/telegram-gateway/app services/telegram-gateway/tests
cd services/telegram-gateway && pytest -q -p no:cacheprovider

docker build -t nexolab-telegram-gateway:test services/telegram-gateway
docker run --rm --network none nexolab-telegram-gateway:test
```

The CI workflow additionally validates the Compose overlay and proves the disabled image
becomes healthy with Docker networking disabled. No real Telegram token or group ID is
needed for TG-02 acceptance.

## Production gate

Do not manually start this adapter on the controlled site as a substitute for deployment
evidence. TG-04 must use the repository-owned guarded deployment path, provision secrets
outside Git, confirm the real numeric group ID, perform one bounded test send, and then
verify restart/retry/offline behavior before enabling the weekday 07:50 delivery path.
