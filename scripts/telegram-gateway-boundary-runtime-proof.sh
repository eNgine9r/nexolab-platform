#!/usr/bin/env bash
set -Eeuo pipefail

if [[ -n "${NEXOLAB_REPO_ROOT:-}" ]]; then
  REPO_ROOT="$(cd "$NEXOLAB_REPO_ROOT" && pwd)"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi
EXPECTED_SOURCE=""
IMAGE_ID=""

usage() {
  cat <<'USAGE'
Usage: telegram-gateway-boundary-runtime-proof.sh \
  --expected-source-sha SHA \
  --image-id sha256:...

Read-only, network-isolated proof that a local Telegram Gateway image is built from the exact Git source tree and enforces the TG-04 bootstrap/cutoff discovery boundary.
USAGE
}

while (($# > 0)); do
  case "$1" in
    --expected-source-sha)
      (($# >= 2)) || { echo "ERROR: --expected-source-sha requires SHA" >&2; exit 64; }
      EXPECTED_SOURCE="$2"
      shift 2
      ;;
    --image-id)
      (($# >= 2)) || { echo "ERROR: --image-id requires image ID" >&2; exit 64; }
      IMAGE_ID="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 64
      ;;
  esac
done

[[ "$EXPECTED_SOURCE" =~ ^[0-9a-f]{40}$ ]] || { echo "ERROR: exact lowercase SHA required" >&2; exit 64; }
[[ "$IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "ERROR: exact image ID required" >&2; exit 64; }
for command in git docker timeout; do
  command -v "$command" >/dev/null 2>&1 || { echo "ERROR: missing command: $command" >&2; exit 69; }
done

docker image inspect "$IMAGE_ID" >/dev/null 2>&1 \
  || { echo "ERROR: Gateway image is unavailable locally" >&2; exit 66; }
GIT=(git -c safe.directory="$REPO_ROOT" -C "$REPO_ROOT")
"${GIT[@]}" rev-parse --verify "${EXPECTED_SOURCE}^{commit}" >/dev/null
EXPECTED_TREE="$("${GIT[@]}" rev-parse "${EXPECTED_SOURCE}:services/telegram-gateway")"
TARGET_REVISION="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE_ID" 2>/dev/null || true)"
TARGET_TREE="$(docker image inspect --format '{{index .Config.Labels "io.nexolab.source-tree"}}' "$IMAGE_ID" 2>/dev/null || true)"
[[ "$TARGET_REVISION" == "$EXPECTED_SOURCE" ]] \
  || { echo "ERROR: target Gateway image source revision mismatch" >&2; exit 65; }
[[ "$TARGET_TREE" == "$EXPECTED_TREE" ]] \
  || { echo "ERROR: target Gateway image source tree mismatch" >&2; exit 65; }

timeout 15s docker run --pull never --rm --network none --read-only \
  --entrypoint /usr/bin/python3 "$IMAGE_ID" -c 'from datetime import UTC, datetime, timedelta
from app.config import Settings
from app.domain import RenderedMessage, ReportSnapshot
from app.service import GatewayRuntime, TelegramDeliveryWorker
import app.service as service_module

now=datetime(2026,9,4,12,0,tzinfo=UTC)
cutoff=now-timedelta(hours=1)
approved_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
rejected_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
post_cutoff_id="cccccccc-cccc-cccc-cccc-cccccccccccc"
org_id="00000000-0000-0000-0000-000000000001"

def snapshot(snapshot_id, scheduled_for):
    return ReportSnapshot(
        id=snapshot_id, organization_id=org_id, profile_id="probe-profile",
        equipment_id="probe-equipment", scheduled_for=scheduled_for,
        payload_sha256="0"*64, payload={},
    )

class Source:
    def __init__(self):
        self.items=[
            snapshot(approved_id, cutoff-timedelta(minutes=20)),
            snapshot(rejected_id, cutoff-timedelta(minutes=10)),
            snapshot(post_cutoff_id, cutoff+timedelta(minutes=10)),
        ]
    def list_snapshots(self, *, limit, offset=0):
        return self.items[offset:offset+limit]

class Outbox:
    def __init__(self): self.ids=[]
    def enqueue(self, snapshot, destination_chat_id, rendered, **kwargs):
        self.ids.append(snapshot.id)

service_module.render_report=lambda snapshot, **kwargs: RenderedMessage(
    text="probe", button_url="https://example.invalid/probe"
)
settings=Settings(
    telegram_enabled=False,
    telegram_destination_chat_id="-1001",
    telegram_mini_app_url_template="https://example.invalid/report_{snapshot_id}",
    telegram_delivery_activation_cutoff_utc=cutoff,
    telegram_delivery_bootstrap_snapshot_ids=approved_id,
    nexolab_backend_auth_mode="none",
    nexolab_backend_organization_id=org_id,
)
outbox=Outbox()
worker=TelegramDeliveryWorker(
    settings, Source(), object(), outbox,
    GatewayRuntime(enabled=False), clock=lambda: now,
)
worker._discover(now)
assert outbox.ids == [approved_id, post_cutoff_id], outbox.ids
' >/dev/null

echo "Gateway boundary image proof: PASS (exact revision/tree, network=none, read-only discovery boundary)"
