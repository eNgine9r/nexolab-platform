#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/nexolab-version-manager.py"

python3 - "$SCRIPT" <<'PY'
import ast
import sys
from pathlib import Path

ast.parse(Path(sys.argv[1]).read_text(encoding="utf-8"))
PY
python3 "$SCRIPT" --help >/dev/null
python3 "$SCRIPT" stage --help >/dev/null
python3 "$SCRIPT" bootstrap --help >/dev/null
python3 "$SCRIPT" run-once --help >/dev/null

grep -q 'pg_dump' "$SCRIPT"
grep -q 'alembic.*current' "$SCRIPT"
grep -q 'verify-offline-bundle.py' "$SCRIPT"
grep -q 'runtime_compatible_schema_heads' "$SCRIPT"
grep -q 'upgrade_from' "$SCRIPT"

if grep -Eq 'compose[^\n]*(down[[:space:]]+-v|--volumes)' "$SCRIPT"; then
  echo "Version manager contains a volume-removal operation" >&2
  exit 1
fi
if grep -Eq '(shell[[:space:]]*=[[:space:]]*True|/bin/bash[[:space:]]+-c)' "$SCRIPT"; then
  echo "Version manager exposes an unrestricted shell execution path" >&2
  exit 1
fi

echo "Version management host-executor contract is safe."
