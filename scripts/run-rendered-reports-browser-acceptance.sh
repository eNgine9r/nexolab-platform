#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_SCRIPT="$ROOT_DIR/scripts/run-reports-browser-acceptance.sh"
TEMP_SCRIPT="$ROOT_DIR/scripts/.run-rendered-reports-browser-acceptance.$$"

cleanup() {
  rm -f "$TEMP_SCRIPT"
}
trap cleanup EXIT

sed \
  's/npm run test:e2e:reports/npm run test:e2e:rendered-reports/' \
  "$SOURCE_SCRIPT" \
  >"$TEMP_SCRIPT"
chmod +x "$TEMP_SCRIPT"

"$TEMP_SCRIPT"
