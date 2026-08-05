#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ACQUISITION_FIXTURE_PORT="${ACQUISITION_FIXTURE_PORT:-18081}"
export ACQUISITION_FIXTURE_REQUESTS_PER_SECOND="${ACQUISITION_FIXTURE_REQUESTS_PER_SECOND:-20}"
export NEXOLAB_ACQUISITION_METRICS_URL="http://127.0.0.1:$ACQUISITION_FIXTURE_PORT/metrics"
export NEXOLAB_DEVICE_AGENT_BASE_URL="http://127.0.0.1:$ACQUISITION_FIXTURE_PORT"

EVIDENCE_DIR="${NEXOLAB_DASHBOARD_EVIDENCE_DIR:-runtime/evidence/authenticated-dashboard-acquisition}"
if [[ "$EVIDENCE_DIR" != /* ]]; then
  EVIDENCE_DIR="$ROOT_DIR/$EVIDENCE_DIR"
fi
mkdir -p "$EVIDENCE_DIR"

FIXTURE_PID=""
cleanup_fixture() {
  if [[ -n "$FIXTURE_PID" ]]; then
    kill "$FIXTURE_PID" >/dev/null 2>&1 || true
    wait "$FIXTURE_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup_fixture EXIT

python3 "$ROOT_DIR/scripts/acquisition-invariant-fixture.py" \
  >"$EVIDENCE_DIR/acquisition-invariant-fixture.log" 2>&1 &
FIXTURE_PID=$!

ready=0
for _ in $(seq 1 50); do
  if curl --fail --silent --show-error \
    "http://127.0.0.1:$ACQUISITION_FIXTURE_PORT/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.1
done
if [[ "$ready" != "1" ]]; then
  printf 'Acquisition invariant fixture did not become ready.\n' >&2
  exit 1
fi

bash "$ROOT_DIR/scripts/run-authenticated-dashboard-acceptance.sh"
