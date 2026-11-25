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
OPERATOR_HOME="${NEXOLAB_OPERATOR_HOME:-$(getent passwd "$OPERATOR" | cut -d: -f6)}"
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

  # ---------------------------------------------------------------------------
  # Candidate summary (#1710 manifest M1-M5). Estimates only; NOTHING is deleted.
  # A candidate is listed only when every gate below holds; everything else is
  # printed as REVIEW or PROTECTED with the reason.
  # ---------------------------------------------------------------------------
  section "Cleanup candidates (estimates only; nothing deleted)"
  total=0
  add() { total=$((total + ${1:-0})); }
  bytes() { du -sbx "$@" 2>/dev/null | awk '{s+=$1} END {print s+0}'; }
  human() { numfmt --to=iec-i --suffix=B "${1:-0}" 2>/dev/null || echo "${1:-0} B"; }

  apt_bytes="$(find /var/cache/apt/archives -maxdepth 1 -name '*.deb' -printf '%s\n' 2>/dev/null | awk '{s+=$1} END {print s+0}')"
  if pgrep -x apt-get >/dev/null || pgrep -x dpkg >/dev/null || pgrep -x apt >/dev/null; then
    echo "M1 REVIEW  apt/dpkg is running; re-run later"
  else
    echo "M1 CLEAN   $(human "$apt_bytes")  downloaded .deb files in /var/cache/apt/archives  ->  sudo apt-get clean"
    add "$apt_bytes"
  fi

  if command -v docker >/dev/null 2>&1; then
    build_cache="$(docker system df --format '{{.Type}}|{{.Reclaimable}}' 2>/dev/null | awk -F'|' '$1=="Build Cache"{print $2}')"
    echo "M2 CLEAN   ${build_cache:-unknown} reclaimable Docker build cache  ->  sudo docker builder prune --force --filter until=168h  (only cache older than 7 days; exact amount reported by the command)"
  fi

  npm_cache="$OPERATOR_HOME/.npm/_cacache"
  if [ -d "$npm_cache" ]; then
    if pgrep -u "$OPERATOR" -f '(^|/)npm( |$)|npx' >/dev/null; then
      echo "M3 REVIEW  npm is running for $OPERATOR; re-run later"
    else
      npm_bytes="$(bytes "$npm_cache")"
      echo "M3 CLEAN   $(human "$npm_bytes")  $npm_cache  ->  sudo -u $OPERATOR npm cache clean --force"
      add "$npm_bytes"
    fi
  fi

  if command -v docker >/dev/null 2>&1; then
    protected_ids="sha256:b96be6cb7ca8a9c71eb94976fe787b35b7a9d5cd2b426c6966a868ca5cc3d15e
sha256:bcfcbb5320017d3f4a205c748f642002ddb70b7fd466a9ebc34e1c780c10244b
sha256:4964c1d4a43ec20e1f53962968e26b7a5e802841eead4abf7a7dd5360649dff1"
    used_ids="$(docker ps -aq | xargs -r docker inspect --format '{{.Image}}' | sort -u)"
    # With the containerd image store `dangling=true` also lists TAGGED images (for example
    # the *-protected-arm64 recovery images). An image is a candidate only when it has no
    # repository tag at all, checked per image; any tag makes it PROTECTED.
    for id in $(docker images -q --filter dangling=true --no-trunc | sort -u); do
      tags="$(docker image inspect --format '{{join .RepoTags " "}}' "$id" 2>/dev/null)"
      if [ -z "$tags" ]; then
        tags="$(docker image ls --no-trunc --format '{{.ID}} {{.Repository}}:{{.Tag}}' 2>/dev/null \
          | awk -v id="$id" '$1 == id && $2 !~ /^<none>/ {print $2}' | tr '\n' ' ')"
      fi
      if printf '%s\n' "$protected_ids" | grep -qx "$id"; then
        echo "M4 PROTECTED $id  (baseline / rollback image)"
      elif printf '%s\n' "$used_ids" | grep -qx "$id"; then
        echo "M4 PROTECTED $id  (used by a container)"
      elif [ -n "$tags" ]; then
        echo "M4 PROTECTED $id  (tagged: ${tags% }; not dangling)"
      elif ! docker image inspect "$id" >/dev/null 2>&1; then
        echo "M4 REVIEW  $id  (cannot inspect; never remove blind)"
      else
        size="$(docker image inspect --format '{{.Size}}' "$id" 2>/dev/null || echo 0)"
        echo "M4 CLEAN   $(human "$size")  dangling image $id  ->  sudo docker image rm $id"
        add "$size"
      fi
    done
  fi

  in_use="$(for pid in $(pgrep -u "$OPERATOR"); do readlink "/proc/$pid/cwd" 2>/dev/null; done | sort -u)"
  units="$(cat /etc/systemd/system/*.service "$OPERATOR_HOME"/.config/systemd/user/*.service 2>/dev/null)"
  for workspace in "$OPERATOR_HOME"/commander-workspaces/*/; do
    [ -d "$workspace" ] || continue
    workspace="$(readlink -f "$workspace")"
    name="$(basename "$workspace")"
    reason=""
    case "$name" in
      nexolab-1638-release-f0295409) reason="holds release evidence (site-activation-report-1638.json)" ;;
    esac
    if [ -z "$reason" ] && printf '%s\n' "$in_use" | grep -q "^$workspace\(/\|$\)"; then reason="working directory of a running process"; fi
    if [ -z "$reason" ] && printf '%s' "$units" | grep -qF "$workspace"; then reason="referenced by a systemd unit"; fi
    if [ -z "$reason" ] && { [ -d "$workspace/.git" ] || [ -f "$workspace/.git" ]; }; then
      dirty="$(as_operator git -C "$workspace" status --porcelain 2>/dev/null | wc -l)"
      unpushed="$(as_operator git -C "$workspace" rev-list --count '@{u}..HEAD' 2>/dev/null || echo unknown)"
      stashes="$(as_operator git -C "$workspace" stash list 2>/dev/null | wc -l)"
      if [ "$dirty" != 0 ] || [ "$unpushed" != 0 ] || [ "$stashes" != 0 ]; then
        reason="git dirty=$dirty unpushed=$unpushed stashes=$stashes"
      fi
    fi
    caches="$(find "$workspace" -xdev -maxdepth 3 -type d \( -name node_modules -o -name .next \) -prune -print 2>/dev/null)"
    [ -n "$caches" ] || continue
    # node_modules/.next inside release, runtime, candidate or artifact folders ARE the
    # deployable release (rollback assets), not caches. Only a plain git checkout has caches.
    if [ -z "$reason" ] && printf '%s\n' "$caches" | sed "s|^$workspace/||" \
        | grep -qiE '(^|/)(release|runtime|candidate[^/]*|artifacts?|build-context|lan|external|bundle)(/|$)'; then
      reason="release/runtime artifact folder, not a cache"
    fi
    if [ -z "$reason" ] && ! { [ -d "$workspace/.git" ] || [ -f "$workspace/.git" ]; }; then
      reason="not a git checkout; contents are not provably regenerable"
    fi
    cache_bytes="$(printf '%s\n' "$caches" | tr '\n' '\0' | xargs -0 du -sbx 2>/dev/null | awk '{s+=$1} END {print s+0}')"
    if [ -n "$reason" ]; then
      echo "M5 REVIEW  $(human "$cache_bytes")  $workspace  ($reason)"
    else
      echo "M5 CLEAN   $(human "$cache_bytes")  regenerable caches in $workspace:"
      printf '%s\n' "$caches" | while read -r cache; do
        echo "             sudo -u $OPERATOR rm -rf --one-file-system '$cache'"
      done
      add "$cache_bytes"
    fi
  done

  echo
  echo "Estimated reclaimable by CLEAN candidates (excluding M2 build cache): $(human "$total")"
  echo "Free now: $(df -h --output=avail / | tail -1 | tr -d ' ')"
} >"$REPORT" 2>&1

echo "Read-only inventory written to $REPORT"
