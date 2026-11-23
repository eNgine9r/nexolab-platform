#!/usr/bin/env bash
# NEXOLAB owner-run, READ-ONLY storage and resource inventory (#1710).
#
# Run as the owner on nexolab-edge-01:
#   sudo bash docs/operations/storage/nexolab-storage-inventory.sh [output-dir]
#
# It never deletes, prunes, stops, restarts or writes anywhere except the one
# report file. It does not read secret contents (.env files, keys), only sizes,
# names, Git metadata and Docker metadata. Every expensive scan is bounded by a
# timeout and stays on the root filesystem (-x). Safe to interrupt at any time.
set -u
umask 077

OUT_DIR="${1:-$PWD}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT="${OUT_DIR}/nexolab-storage-inventory-${STAMP}.txt"
OPERATOR="${NEXOLAB_OPERATOR:-nexolab}"
OPERATOR_HOME="$(getent passwd "$OPERATOR" | cut -d: -f6)"
SCAN_TIMEOUT="${NEXOLAB_INVENTORY_SCAN_TIMEOUT:-900}"

[ "$(id -u)" = 0 ] || { echo "Run with sudo (read-only inventory needs to see protected paths)." >&2; exit 1; }
[ -n "$OPERATOR_HOME" ] || { echo "Unknown operator account $OPERATOR" >&2; exit 1; }

section() { printf '\n===== %s =====\n' "$*"; }
sizes() { # sizes <max-depth> <path>...
  local depth="$1"; shift
  local path
  for path in "$@"; do
    [ -e "$path" ] || { echo "(absent) $path"; continue; }
    timeout "$SCAN_TIMEOUT" nice -n 19 ionice -c3 du -xh --max-depth="$depth" "$path" 2>/dev/null | sort -rh | head -40
  done
}
as_operator() { runuser -u "$OPERATOR" -- "$@"; }

{
  echo "NEXOLAB storage inventory ${STAMP} on $(hostname), read-only"
  section "Filesystems"
  df -h / /boot/firmware 2>/dev/null
  df -i /
  section "Memory and load"
  free -m; cat /proc/loadavg; swapon --show

  section "Largest top-level areas (root filesystem only)"
  sizes 1 /
  section "Operator home"
  sizes 1 "$OPERATOR_HOME"
  section "Commander workspaces"
  sizes 1 "$OPERATOR_HOME/commander-workspaces"
  section "Deployment checkout runtime (evidence, releases, deployments)"
  sizes 2 "$OPERATOR_HOME/nexolab-platform/runtime"
  section "Protected system areas"
  sizes 1 /var/lib/docker /var/lib/nexolab /var/backups/nexolab /root /var/cache/apt /var/log

  section "Regenerable build caches inside operator workspaces (candidates only)"
  timeout "$SCAN_TIMEOUT" find "$OPERATOR_HOME" -xdev -maxdepth 4 -type d \
    \( -name node_modules -o -name .next -o -name .turbo -o -name coverage \
       -o -name test-results -o -name playwright-report -o -name __pycache__ -o -name .pytest_cache \) \
    -prune -print0 2>/dev/null | xargs -0 -r du -sh 2>/dev/null | sort -rh | head -60
  section "Operator package caches"
  sizes 0 "$OPERATOR_HOME/.npm" "$OPERATOR_HOME/.cache" "$OPERATOR_HOME/.nvm/.cache"

  section "Git state of operator checkouts (in-use and unpushed work is PROTECTED)"
  declare -A seen=()
  for repo in "$OPERATOR_HOME"/nexolab-platform "$OPERATOR_HOME"/commander-workspaces/*/ "$OPERATOR_HOME"/*/; do
    [ -d "$repo/.git" ] || [ -f "$repo/.git" ] || continue
    repo="$(readlink -f "$repo")"
    [ -z "${seen[$repo]:-}" ] || continue
    seen[$repo]=1
    branch="$(as_operator git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null)"
    head="$(as_operator git -C "$repo" rev-parse --short HEAD 2>/dev/null)"
    dirty="$(as_operator git -C "$repo" status --porcelain 2>/dev/null | wc -l)"
    unpushed="$(as_operator git -C "$repo" rev-list --count '@{u}..HEAD' 2>/dev/null || echo 'no-upstream')"
    stashes="$(as_operator git -C "$repo" stash list 2>/dev/null | wc -l)"
    last="$(as_operator git -C "$repo" log -1 --format=%cs 2>/dev/null)"
    printf '%s\tbranch=%s head=%s dirty=%s unpushed=%s stashes=%s last_commit=%s\n' \
      "$repo" "$branch" "$head" "$dirty" "$unpushed" "$stashes" "$last"
  done

  section "Directories in use by running processes (PROTECTED)"
  for pid in $(pgrep -u "$OPERATOR"); do
    printf '%s\t%s\t%s\n' "$pid" "$(readlink "/proc/$pid/cwd" 2>/dev/null)" "$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | cut -c1-160)"
  done | sort -k2 -u
  section "systemd units referencing operator paths (PROTECTED)"
  grep -ls "$OPERATOR_HOME" /etc/systemd/system/*.service /etc/systemd/system/*.timer \
    "$OPERATOR_HOME"/.config/systemd/user/*.service 2>/dev/null

  if command -v docker >/dev/null 2>&1; then
    section "Docker disk usage"
    docker system df
    section "Docker containers (all states, with size)"
    docker ps -a --size --format '{{.ID}}\t{{.Names}}\t{{.State}}\t{{.Image}}\t{{.Size}}\t{{.CreatedAt}}'
    section "Docker images (digests, created, size)"
    docker images --digests --no-trunc --format '{{.ID}}\t{{.Repository}}:{{.Tag}}\t{{.Digest}}\t{{.CreatedSince}}\t{{.Size}}'
    section "Image IDs used by any container (PROTECTED)"
    docker ps -aq | xargs -r docker inspect --format '{{.Image}}' | sort -u
    section "Dangling images (candidates only after cross-checking the protected lists)"
    docker images --filter dangling=true --no-trunc --format '{{.ID}}\t{{.CreatedSince}}\t{{.Size}}'
    section "Docker volumes (PROTECTED: never prune)"
    docker volume ls --format '{{.Name}}\t{{.Driver}}'
    docker system df -v 2>/dev/null | sed -n '/^Local Volumes space usage:/,/^Build cache usage:/p'
    section "Docker build cache"
    docker builder du 2>/dev/null | tail -5

    section "PostgreSQL database and largest relations (read-only queries)"
    pg="$(docker ps -q --filter label=com.docker.compose.service=postgres | head -1)"
    if [ -n "$pg" ]; then
      docker exec "$pg" sh -c 'psql -X -A -U "${POSTGRES_USER:-nexolab}" -d "${POSTGRES_DB:-nexolab}" -c "select pg_size_pretty(pg_database_size(current_database()));" -c "select relname, pg_size_pretty(pg_total_relation_size(c.oid)) from pg_class c join pg_namespace n on n.oid=c.relnamespace where relkind in (\$\$r\$\$,\$\$m\$\$) and nspname not in (\$\$pg_catalog\$\$,\$\$information_schema\$\$) order by pg_total_relation_size(c.oid) desc limit 12;"' 2>&1
    else
      echo "postgres container not found by compose label; skipped"
    fi
  fi

  section "Journal"
  journalctl --disk-usage
} >"$REPORT" 2>&1

echo "Read-only inventory written to $REPORT"
