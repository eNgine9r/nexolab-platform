# Telegram gateway

The NEXOLAB Telegram gateway is an **optional online delivery adapter** for persisted
refrigeration morning-report snapshots. PostgreSQL, telemetry acquisition, TG-01 report
generation and the LOCAL_LAN dashboard remain authoritative and continue without it.

Initial acceptance target: Telegram group historically referred to as `Тест лаб`; the real Bot API acceptance on 2026-09-03 observed the current title `TestLAB`. The group title is human evidence
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

## TG-03 Mini App boundary

TG-03 adds an optional read-only Mini App surface without changing the authority of TG-01
snapshots. The browser sends raw Telegram `initData` to the same-origin NEXOLAB route;
the Telegram gateway validates the signed payload and age, resolves the validated Telegram
user through an explicit local identity-link file, and the Telemetry Service re-authorizes
that linked NEXOLAB identity for `reports.read` in the caller's exact organization before
returning the persisted snapshot. Browser actor, identity and organization values are never
authoritative, and `initDataUnsafe` is not used for authentication.

When the optional Compose profile is enabled, the gateway publishes port `8090` only on
`127.0.0.1`. This exists solely so the host-managed Next.js Dashboard can proxy the Mini App
request without exposing the gateway on the LAN or internet. Containerized Dashboard builds
may instead use the exact internal DNS endpoint `http://telegram-gateway:8090`; the Next.js
proxy rejects other hosts, schemes, ports, paths and client-supplied authority fields.

Mini App authentication uses the existing bot-token secret plus an additional root-managed
read-only file:

```text
/etc/nexolab/telegram/identity-links.json
```

Expected structure (IDs below are placeholders only):

```json
{
  "version": 1,
  "links": [
    {
      "telegram_user_id": 123456789,
      "organization_id": "00000000-0000-0000-0000-000000000001",
      "identity_id": "11111111-1111-1111-1111-111111111111"
    }
  ]
}
```

Do not commit the real mapping. Duplicate Telegram-user/organization entries, malformed UUIDs,
missing files and oversized mappings fail closed before Mini App readiness. `TELEGRAM_MINIAPP_ENABLED`
defaults to `false`, and TG-03 software acceptance uses only synthetic signed fixtures.

The `/telegram-miniapp` route loads Telegram's official Web App JavaScript only on that isolated
surface. The ordinary LOCAL_LAN dashboard and offline bundle do not depend on Telegram JS or
internet. The Mini App renders the immutable persisted report and explicitly labels it as a
saved, non-live report; it does not recompute KPIs from raw telemetry. Thermodynamic metrics and
refrigerant remain unavailable when the accepted NEXOLAB data model does not provide them.

Real BotFather configuration, real bot token provisioning, real identity-link values, group
membership, Telegram phone/WebView/Tailscale acceptance and production enablement remain TG-04
/ #825 gates and must not be inferred from TG-03 software tests.

## TG-04 real group identification helper

After the dedicated bot has been added to the intended laboratory group and the root-owned bot token exists,
use the repository helper from the TG-04 branch to identify the destination without exposing
credentials or Telegram user payloads:

```bash
cd ~/nexolab-platform/services/telegram-gateway
sudo -n env PYTHONPATH="$PWD" python3 -m app.group_identification
```

The helper performs only `getMe` and `getUpdates`, matches the exact current group/supergroup title
`TestLAB`, and prints one sanitized JSON object containing bot id/username plus the matched
group title/type/chat id/update id. It never prints the bot token or Telegram user/profile data.

Do not commit the observed chat id. Record it only in protected runtime configuration/evidence
for TG-04. If no matching pending update exists, create one harmless group event (for example,
remove/re-add the bot or post a command mentioning the bot) and run the helper again; do not
disable Telegram privacy mode merely for discovery.

## TG-04 protected backend/runtime provisioning

After real `TestLAB` group identity is confirmed, prepare the gateway service principal and disabled host runtime configuration through the repository helper:

```bash
cd ~/nexolab-platform/services/telegram-gateway
sudo -n env PYTHONPATH="$PWD" python3 -m app.runtime_provisioning
```

The helper prompts locally for an existing NEXOLAB administrator username/password with password echo disabled. It authenticates only against the configured private/local NEXOLAB backend, derives the one administrator-managed organization, and creates `nexolab-telegram` only when absent with product role `laboratory_technician` and the single explicit grant `reports.read`. Admin/access/refresh tokens and generated passwords are never printed.

The generated backend password is written root-only to `/etc/nexolab/telegram/nexolab-backend-password`. A root-only `.nexolab-backend-password.pending` file makes an interrupted create recoverable without silent credential rotation. If an existing `nexolab-telegram` account has no managed final/pending secret, the helper fails closed and does not reset the account automatically.

The same helper re-confirms the current `TestLAB` group through `getMe/getUpdates` and writes `/etc/nexolab/telegram/telegram.env` with the observed numeric destination, organization and Main Mini App direct-link template. Both `TELEGRAM_ENABLED` and `TELEGRAM_MINIAPP_ENABLED` remain `false`; this preparation does not start the gateway, send a Telegram message, alter Tailscale Serve or perform production cutover.

Identity linking is separate. Do not map a Telegram user to the `nexolab-telegram` service account merely because it exists; the Mini App linked identity must be an explicitly authorized NEXOLAB user/principal with `reports.read`.

## TG-04 explicit human identity linking

After protected backend/runtime provisioning succeeds, link one real Telegram user to one existing authorized NEXOLAB identity:

```bash
cd ~/nexolab-platform/services/telegram-gateway
sudo -n env PYTHONPATH="$PWD" python3 -m app.identity_link_provisioning
```

The helper prompts locally for an administrator credential and for the existing NEXOLAB username to link; pressing Enter for the target uses the administrator username. The selected NEXOLAB user must be active and already have effective `reports.read`. The helper does not grant or widen that user's permissions.

It prints one ephemeral `/nexolab_link <random-challenge>` command and asks that exact command be sent in the **private chat** with the reported bot. Only a fresh exact private-chat message whose chat identity equals its sender identity is accepted. Group messages, stale updates, wrong commands and unrelated Telegram users are ignored.

On success the numeric Telegram user id is written only to root-owned `/etc/nexolab/telegram/identity-links.json`, together with the selected organization/identity UUID. The Telegram user id is not printed in the final sanitized result. Existing exact links are idempotent; conflicting Telegram-user or NEXOLAB-identity mappings fail closed. `TELEGRAM_ENABLED` and `TELEGRAM_MINIAPP_ENABLED` remain unchanged and disabled until the later explicit cutover gate.

## TG-04 nonroot runtime secret access

The distroless Telegram Gateway runs as the pinned `nonroot` identity (`uid=65532`, `gid=65532`). A root-owned `0700` secret directory with `0600` files cannot be read through the Compose bind mount by that runtime identity. Do not solve this by running the gateway as root or by making secrets world-readable.

After backend provisioning and identity linking are complete, prepare only the three runtime-consumed secret files for the pinned runtime group:

```bash
cd ~/nexolab-platform/services/telegram-gateway
sudo -n env PYTHONPATH="$PWD" python3 -m app.runtime_secret_permissions
```

The helper requires root ownership, regular non-hardlinked files and no existing group/other write permission. It keeps the directory and files root-owned, sets only group `65532` for the gateway runtime, applies directory mode `0750` and file mode `0640`, and refuses symlinks or malformed permission state. It changes no secret value, does not print secret contents and does not start the gateway. `/etc/nexolab/telegram/telegram.env` and any pending provisioning secret remain outside this runtime-readable set.

Actual gateway start remains part of the guarded TG-04 controlled deployment. Do not manually start the adapter as a substitute for deployment evidence.

## TG-04 Stage 1 — Mini App runtime only

After the TG-04 exact PR head is fully GREEN and the Product Owner explicitly approves the controlled site action, use the dedicated guarded path rather than a manual Compose start:

```bash
cd ~/nexolab-platform
sudo scripts/deploy-telegram-miniapp-stage1.sh \
  --expected-source-sha <exact-green-pr-sha> \
  --approve-miniapp-only
```

Stage 1 builds the gateway from that exact tracked source, prepares only the three runtime-consumed protected files for the pinned nonroot group, and starts only `telegram-gateway` with Compose `--no-deps --no-build`. It forces `TELEGRAM_ENABLED=false` and `TELEGRAM_MINIAPP_ENABLED=true`, so the delivery worker remains stopped while signed Mini App requests can be validated.

The guard records evidence under `runtime/evidence/tg04-telegram-stage1-*`, verifies Dashboard/Telemetry/frontend health before and after, requires unchanged identities for the existing PostgreSQL/MQTT/MinIO/Telemetry/Device Agent containers, and proves Tailscale Serve topology did not change. On a Stage 1 failure it removes only the newly created gateway container and leaves the persistent delivery volume intact. It never uses `compose down`, deletes volumes, sends a report, enables the weekday schedule, or touches Modbus/hardware.

## TG-04 TestLAB forum-topic destination

TestLAB forum delivery is modeled as an exact destination of `chat_id + message_thread_id`.
`TELEGRAM_DESTINATION_MESSAGE_THREAD_ID` is optional: when unset, delivery remains in Telegram
General; when set to a positive integer, both the persistent worker and controlled one-shot send
include that exact `message_thread_id`. The durable outbox uses the same topic-aware identity, so a
historical General delivery and a delivery of the same snapshot to a forum topic do not alias.
Legacy outbox rows migrate transactionally as General (`thread = 0` internally) without deletion or
re-send, and a topic-configured worker only claims rows for its exact current destination.

Do not put a numeric topic id in Git, issue comments, screenshots or operator evidence. Capture the
intended topic through the protected helper after repository/runtime acceptance:

```bash
cd ~/nexolab-platform/services/telegram-gateway
sudo env PYTHONPATH="$PWD" python3 -m app.topic_provisioning
```

The helper requires persistent delivery to remain disabled. It prints a random one-time
`/nexolab_topic_...` command. Post that exact command in the intended TestLAB forum topic and then
press Enter in the terminal. The helper accepts only an exact pending update from the already
configured TestLAB group with `is_topic_message=true` and one unambiguous positive
`message_thread_id`; posting the challenge in General fails closed. The numeric topic id is written
only to root-protected `telegram.env` and is omitted from the sanitized result. Existing secret
directory permissions are preserved.

After topic capture, keep `TELEGRAM_ENABLED=false` and `DAILY_REPORTS_SCHEDULER_ENABLED=false`.
Run the exact-snapshot no-send dry-run before any real topic test. A real topic test remains a
separate Product Owner gate.

## TG-04 exact-snapshot controlled one-shot delivery

Do not enable the long-running delivery worker for the first real TestLAB acceptance send.
`TelegramDeliveryWorker` intentionally discovers eligible snapshots in pages, so it is not an
"exactly one message" acceptance tool. Use `app.controlled_send` from an immutable gateway image
instead. The command fetches one explicit snapshot ID, verifies its expected payload SHA-256 and
organization, and can claim only that snapshot's exact durable outbox key.

The persistent gateway must remain `TELEGRAM_ENABLED=false`, and the weekday report scheduler must
remain disabled. The one-shot command refuses to run if its own resolved `TELEGRAM_ENABLED` is
`true`. `--dry-run` and `--approve-single-send` are mutually exclusive; a real call requires the
literal acknowledgement `SEND_EXACT_SNAPSHOT_ONCE`.

Before any controlled dry-run, verify the repository is clean and the site safety boundary is
still closed:

```bash
cd ~/nexolab-platform
SOURCE_SHA="$(git rev-parse HEAD)"
test -z "$(git status --porcelain)"
test "$(git rev-parse origin/main)" = "$SOURCE_SHA"

curl -fsS http://127.0.0.1:8090/health/ready | python3 -c '
import json,sys
p=json.load(sys.stdin)
assert p["delivery_enabled"] is False and p["running"] is False
assert p["last_send_at"] is None
'
```

Also prove the scheduler remains fail-closed and build a gateway image from that exact source:

```bash
docker inspect nexolab-central-telemetry-service-1 \
  --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -Fx 'DAILY_REPORTS_SCHEDULER_ENABLED=false'

IMAGE_TAG="nexolab-telegram-gateway:tg04-one-shot-${SOURCE_SHA:0:12}"
docker build --tag "$IMAGE_TAG" services/telegram-gateway
IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE_TAG")"
test -n "$IMAGE_ID"
```

Keep the real snapshot ID and expected digest in the operator shell only. Do not put the numeric
Telegram destination, bot token, backend password, rendered report body or Telegram identity in
shell arguments, evidence, screenshots or Git. The protected env file supplies the destination
inside the ephemeral container:

```bash
SNAPSHOT_ID='<exact-persisted-snapshot-uuid>'
EXPECTED_SHA256='<exact-64-char-payload-sha256>'
CENTRAL_ENV="$PWD/infrastructure/compose/.env.central"
TELEGRAM_ENV='/etc/nexolab/telegram/telegram.env'

sudo env TELEGRAM_GATEWAY_IMAGE="$IMAGE_TAG" docker compose \
  --env-file "$CENTRAL_ENV" \
  --env-file "$TELEGRAM_ENV" \
  -f infrastructure/compose/compose.central.yaml \
  -f infrastructure/compose/compose.telegram.yaml \
  --profile telegram \
  run --rm --no-deps --pull never \
  -e TELEGRAM_ENABLED=false \
  telegram-gateway \
  -m app.controlled_send \
  --snapshot-id "$SNAPSHOT_ID" \
  --expected-payload-sha256 "$EXPECTED_SHA256" \
  --dry-run
```

A successful dry-run returns sanitized JSON with `status=dry_run_ready`, the exact snapshot ID,
payload digest and `delivery_state=absent` or `pending`. It makes no Telegram API call and does not
create or transition an outbox delivery. `already_sent` is also a safe idempotent result. Any
`sending`, `retry_wait`, `failed`, digest mismatch or `duplicate_risk` state is a stop condition;
do not repair/reset it ad hoc.

Only after the dry-run evidence is accepted and the Product Owner separately authorizes exactly
one real TestLAB message, repeat the same ephemeral command and replace `--dry-run` with:

```text
--approve-single-send SEND_EXACT_SNAPSHOT_ONCE
```

One invocation makes at most one Telegram `sendMessage` request. A successful response is committed
to the same durable SQLite outbox as `sent`; rerunning the exact command becomes an idempotent
`already_sent` no-op. A Telegram API failure is terminal for this controlled attempt rather than
being placed on background retry. Retryable/unknown failures set duplicate risk and require a new
explicit resolution gate before any further send attempt.

After the attempt, re-run the health/scheduler checks above. The persistent gateway must still
show delivery disabled and worker stopped, and the weekday scheduler must still be `false`. Do not
turn on the permanent worker or 07:50 schedule as part of this one-shot acceptance step.
