#!/usr/bin/env bash
# NEXOLAB development session bootstrap (#1710).
# Owner-installed to /usr/local/lib/nexolab-dev/ (root-owned, 0755).
# Runs as nexolab-dev inside the sandboxed tmux session started by
# nexolab-dev-session.service. It never touches production: it only reads the
# public health endpoints, the local disk/memory figures and the workspace.
#
# Order: wait for production readiness -> resource gates -> recovery snapshot
# -> optional automatic Claude resume (opt-in flag file) -> interactive shell.
set -u

REPO="${NEXOLAB_DEV_REPO:-/home/nexolab-dev/nexolab-platform}"
STATE_DIR="${HOME}/.local/state/nexolab-dev"
CONFIG_DIR="${HOME}/.config/nexolab-dev"
AUTO_RESUME_FLAG="${CONFIG_DIR}/auto-resume"
DEVICE_AGENT_HEALTH="${NEXOLAB_DEVICE_AGENT_HEALTH:-http://127.0.0.1:8081/health}"
# Internal readiness endpoints, first ready wins. Loopback is the stable
# network-independent endpoint (#1734); the former LAN address stays as the
# #1733 compatibility alias until WP2 cutover. Never a DHCP address.
TELEMETRY_READY_URLS="${NEXOLAB_TELEMETRY_READY_URLS:-${NEXOLAB_TELEMETRY_READY:-http://127.0.0.1:8082/health/ready http://172.18.48.66:8082/health/ready}}"
MIN_FREE_GIB="${NEXOLAB_DEV_MIN_FREE_GIB:-20}"
MIN_HOST_AVAILABLE_MIB="${NEXOLAB_DEV_MIN_HOST_AVAILABLE_MIB:-900}"
READINESS_WAIT_SECONDS="${NEXOLAB_DEV_READINESS_WAIT_SECONDS:-900}"
# After the first window fails, keep re-checking (bounded) so the session
# resumes on its own once production recovers. The guard is never bypassed.
READINESS_RETRY_SECONDS="${NEXOLAB_DEV_READINESS_RETRY_SECONDS:-43200}"
READINESS_RETRY_INTERVAL="${NEXOLAB_DEV_READINESS_RETRY_INTERVAL:-60}"
export PATH="${HOME}/.local/bin:${HOME}/.local/node/bin:${PATH}"

mkdir -p "$STATE_DIR"
LOG="${STATE_DIR}/session-start.log"
SNAPSHOT="${STATE_DIR}/last-recovery-snapshot.txt"

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG"; }

READY_URL=""
telemetry_ready() {
  local url
  for url in $TELEMETRY_READY_URLS; do
    if curl -fsS -m 5 "$url" 2>/dev/null | grep -q '"status": *"ready"'; then
      READY_URL="$url"
      return 0
    fi
  done
  return 1
}

log "session start; boot=$(uptime -s 2>/dev/null || echo unknown)"

# 1. Production first: wait (bounded) until telemetry reports ready.
waited=0
until telemetry_ready; do
  if [ "$waited" -ge "$READINESS_WAIT_SECONDS" ]; then
    break
  fi
  sleep 30
  waited=$((waited + 30))
done

# 2. Gates.
evaluate_gates() {
gate_ok=1
reasons=()
if telemetry_ready; then
  log "telemetry ready after ${waited}s via ${READY_URL}"
else
  gate_ok=0
  reasons+=("telemetry not ready after ${waited}s")
fi
free_gib="$(df -BG --output=avail / | tail -1 | tr -dc '0-9')"
if [ "${free_gib:-0}" -lt "$MIN_FREE_GIB" ]; then
  gate_ok=0
  reasons+=("free disk ${free_gib} GiB < ${MIN_FREE_GIB} GiB")
fi
available_mib="$(awk '/^MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo)"
if [ "${available_mib:-0}" -lt "$MIN_HOST_AVAILABLE_MIB" ]; then
  gate_ok=0
  reasons+=("host MemAvailable ${available_mib} MiB < ${MIN_HOST_AVAILABLE_MIB} MiB")
fi
log "gates: free_disk=${free_gib}GiB host_available=${available_mib}MiB result=$([ "$gate_ok" = 1 ] && echo PASS || echo FAIL)"
}
evaluate_gates

# 2b. Bounded re-check: production first, then resume automatically.
if [ "$gate_ok" != 1 ]; then
  log "gates FAILED: ${reasons[*]}; re-checking every ${READINESS_RETRY_INTERVAL}s for up to ${READINESS_RETRY_SECONDS}s"
  echo "Development gates FAILED: ${reasons[*]}. Production has priority; re-checking automatically."
  retry_deadline=$((waited + READINESS_RETRY_SECONDS))
  while [ "$gate_ok" != 1 ] && [ "$waited" -lt "$retry_deadline" ]; do
    sleep "$READINESS_RETRY_INTERVAL"
    waited=$((waited + READINESS_RETRY_INTERVAL))
    if telemetry_ready; then
      evaluate_gates
    fi
  done
fi

# 3. Recovery snapshot (read-only facts for the operator and the agent).
{
  echo "Recovery snapshot $(date -u +%Y-%m-%dT%H:%M:%SZ), boot $(uptime -s 2>/dev/null)"
  echo "--- device agent"
  curl -fsS -m 5 "$DEVICE_AGENT_HEALTH" 2>/dev/null | head -c 400; echo
  echo "--- telemetry"
  for url in $TELEMETRY_READY_URLS; do echo "$url"; curl -fsS -m 5 "$url" 2>/dev/null | head -c 400; echo; done
  echo "--- workspace"
  if cd "$REPO" 2>/dev/null; then
    git status -sb 2>&1 | head -20
    echo "stashes: $(git stash list 2>/dev/null | wc -l)"
    git worktree list 2>&1
    git log --oneline -3 2>&1
  fi
} >"$SNAPSHOT" 2>&1
log "recovery snapshot written to $SNAPSHOT"

cd "$REPO" 2>/dev/null || cd "$HOME"

RECOVERY_PROMPT="The Raspberry Pi restarted and this development session was started automatically. \
Read ${SNAPSHOT}, then recover the interrupted NEXOLAB task from repository state, \
.project checkpoints, Git branches, open Pull Requests and GitHub Issues. Check for interrupted \
operations and incomplete cleanup before continuing, and do not repeat completed work. \
Follow AGENTS.md and the operating standard. Do not modify or restart production services, \
do not reboot the host, and stop at hard blockers."

# 4. Optional automatic resume (owner opt-in), never in a loop.
if [ "$gate_ok" = 1 ] && [ -f "$AUTO_RESUME_FLAG" ] && command -v claude >/dev/null 2>&1; then
  log "auto-resume enabled: starting claude --continue"
  claude --continue --permission-mode auto "$RECOVERY_PROMPT"
  log "claude exited with status $?"
elif [ "$gate_ok" = 1 ]; then
  log "auto-resume not enabled; waiting for the operator"
  echo "Gates passed. Resume with:  claude --continue"
else
  log "gates FAILED: ${reasons[*]}; Claude not started"
  echo "Development gates FAILED: ${reasons[*]}"
  echo "Production has priority. Investigate before starting Claude."
fi

# 5. Keep the tmux session usable for the operator.
exec bash -l
