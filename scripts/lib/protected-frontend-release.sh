#!/usr/bin/env bash
# Existing Google gateway stays in place. Only its frontend release is replaced.
EXTERNAL_FRONTEND_ENABLED=0
EXTERNAL_FRONTEND_TOUCHED=0
EXTERNAL_FRONTEND_RELEASE_DIR=""
EXTERNAL_FRONTEND_CANDIDATE_UNIT=""

nexolab_external_frontend_preflight() {
  local unit=/etc/systemd/system/nexolab-external-frontend.service
  if [[ ! -f "$unit" ]]; then
    [[ -z "$EXTERNAL_FRONTEND_ARTIFACT_INPUT" && -z "$EXTERNAL_FRONTEND_ORIGIN" ]] || {
      log "ERROR: protected frontend is not installed; this updater never publishes a gateway"
      return 70
    }
    return 0
  fi
  [[ "$RUNTIME_MODE" == lan && -d "$EXTERNAL_FRONTEND_ARTIFACT_INPUT" && -n "$EXTERNAL_FRONTEND_ORIGIN" ]] || {
    log "ERROR: installed protected frontend requires --external-frontend-artifact and --external-origin"
    return 70
  }
  [[ -z "$(systemctl show nexolab-external-frontend.service -p DropInPaths --value)" ]] || {
    log "ERROR: protected frontend has service overrides requiring explicit review"
    return 70
  }
  EXTERNAL_FRONTEND_ARTIFACT_DIR="$(cd "$EXTERNAL_FRONTEND_ARTIFACT_INPUT" && pwd -P)"
  cp "$unit" "$AUDIT_DIR/external-unit-before.service"
  systemctl is-active nexolab-external-frontend.service > "$AUDIT_DIR/external-active-before.txt" || {
    log "ERROR: current protected frontend must be active before a handoff"
    return 70
  }
  python3 "$SCRIPT_DIR/nexolab-protected-frontend.py" validate \
    --unit "$AUDIT_DIR/external-unit-before.service" --nginx /opt/nexolab-external/nginx.conf \
    --origin "$EXTERNAL_FRONTEND_ORIGIN" --organization "$FRONTEND_ORGANIZATION_ID" --api "$NEXOLAB_API_BASE_URL" || return
  python3 "$SCRIPT_DIR/nexolab-protected-frontend.py" snapshot --origin "$EXTERNAL_FRONTEND_ORIGIN" \
    --output "$AUDIT_DIR/external-identity-before.json" || return
  nexolab_frontend_verify_profile "$EXTERNAL_FRONTEND_ARTIFACT_DIR/frontend-runtime-contract.txt" true || return
  [[ "$(tr -d '[:space:]' < "$EXTERNAL_FRONTEND_ARTIFACT_DIR/frontend-source-sha.txt")" == "$CURRENT_HEAD" ]] || {
    log "ERROR: protected and LAN artifacts must share the selected source commit"
    return 70
  }
  EXTERNAL_FRONTEND_ENABLED=1
}

nexolab_external_frontend_cleanup_candidate() {
  [[ -n "$EXTERNAL_FRONTEND_CANDIDATE_UNIT" ]] || return 0
  if [[ "$(systemctl show "$EXTERNAL_FRONTEND_CANDIDATE_UNIT" -p LoadState --value)" != not-found ]]; then
    sudo systemctl stop "$EXTERNAL_FRONTEND_CANDIDATE_UNIT" || return
  fi
  EXTERNAL_FRONTEND_CANDIDATE_UNIT=""
}

nexolab_external_frontend_prepare() {
  [[ "$EXTERNAL_FRONTEND_ENABLED" == 1 ]] || return 0
  local websocket="${EXTERNAL_FRONTEND_ORIGIN/#https:/wss:}/api/v1/telemetry/live"
  local port=3102
  if ss -ltn | awk '{print $4}' | grep -Eq "(^|:)$port$"; then
    log "ERROR: protected candidate verification port is already in use: $port"
    return 70
  fi
  EXTERNAL_FRONTEND_RELEASE_DIR="$REPO/runtime/external-frontend-releases/${CURRENT_HEAD}-${STAMP}"
  mkdir -p "$REPO/runtime/external-frontend-releases"
  nexolab_frontend_prepare_release_source "$REPO" "$CURRENT_HEAD" "$EXTERNAL_FRONTEND_RELEASE_DIR" "" || return
  nexolab_frontend_import_artifact "$EXTERNAL_FRONTEND_ARTIFACT_DIR" "$REPO" \
    "$EXTERNAL_FRONTEND_RELEASE_DIR" "$CURRENT_HEAD" live "$EXTERNAL_FRONTEND_ORIGIN" \
    "$websocket" local "$FRONTEND_ORGANIZATION_ID" "$AUDIT_DIR/external-artifact-import.txt" true || return
  python3 "$SCRIPT_DIR/nexolab-protected-frontend.py" render \
    --origin "$EXTERNAL_FRONTEND_ORIGIN" --unit "$AUDIT_DIR/external-unit-before.service" \
    --release "$EXTERNAL_FRONTEND_RELEASE_DIR" --node "$(command -v node)" \
    --api "$NEXOLAB_API_BASE_URL" --output "$AUDIT_DIR/external-unit-candidate.service" \
    --source "$CURRENT_HEAD" --build "$(cat "$EXTERNAL_FRONTEND_RELEASE_DIR/.next/BUILD_ID")" || return
  EXTERNAL_FRONTEND_CANDIDATE_UNIT="nexolab-external-candidate-$STAMP.service"
  sudo systemd-run --unit "$EXTERNAL_FRONTEND_CANDIDATE_UNIT" --collect --service-type=exec \
    --property "User=$(id -un)" --property "Group=$(id -gn)" \
    --property "WorkingDirectory=$EXTERNAL_FRONTEND_RELEASE_DIR" \
    --property MemoryMax=768M --property MemorySwapMax=0 --property TasksMax=64 \
    --property NoNewPrivileges=yes --property PrivateTmp=yes \
    --setenv NODE_ENV=production --setenv NEXT_TELEMETRY_DISABLED=1 \
    --setenv NODE_OPTIONS=--max-old-space-size=384 \
    --setenv NEXOLAB_EXTERNAL_HTTPS_STAGE=true \
    --setenv "NEXOLAB_SERVER_API_BASE_URL=$NEXOLAB_API_BASE_URL" \
    "$(command -v node)" "$EXTERNAL_FRONTEND_RELEASE_DIR/node_modules/next/dist/bin/next" \
    start --hostname 127.0.0.1 --port "$port" || return
  local probe_rc=0
  python3 "$SCRIPT_DIR/nexolab-protected-frontend.py" probe --origin "$EXTERNAL_FRONTEND_ORIGIN" \
    --port "$port" --source "$CURRENT_HEAD" \
    --build "$(cat "$EXTERNAL_FRONTEND_RELEASE_DIR/.next/BUILD_ID")" || probe_rc=$?
  nexolab_external_frontend_cleanup_candidate || return
  return "$probe_rc"
}

nexolab_external_frontend_rollback() {
  [[ "$EXTERNAL_FRONTEND_TOUCHED" == 1 ]] || return 0
  sudo systemctl stop nexolab-external-frontend.service || return
  sudo install -m 0644 "$AUDIT_DIR/external-unit-before.service" /etc/systemd/system/nexolab-external-frontend.service || return
  sudo systemctl daemon-reload || return
  if [[ "$(cat "$AUDIT_DIR/external-active-before.txt")" == active ]]; then
    sudo systemctl start nexolab-external-frontend.service || return
    python3 "$SCRIPT_DIR/nexolab-protected-frontend.py" probe --origin "$EXTERNAL_FRONTEND_ORIGIN" \
      --identity "$AUDIT_DIR/external-identity-before.json" || return
  fi
  EXTERNAL_FRONTEND_TOUCHED=0
  log "Restored previous protected frontend unit and its original identity file"
}

nexolab_external_frontend_activate() {
  [[ "$EXTERNAL_FRONTEND_ENABLED" == 1 ]] || return 0
  EXTERNAL_FRONTEND_TOUCHED=1
  sudo systemctl stop nexolab-external-frontend.service || return
  sudo install -m 0644 "$AUDIT_DIR/external-unit-candidate.service" /etc/systemd/system/nexolab-external-frontend.service || return
  sudo systemctl daemon-reload || return
  sudo systemctl start nexolab-external-frontend.service || return
  python3 "$SCRIPT_DIR/nexolab-protected-frontend.py" probe --origin "$EXTERNAL_FRONTEND_ORIGIN" \
    --source "$CURRENT_HEAD" --build "$(cat "$EXTERNAL_FRONTEND_RELEASE_DIR/.next/BUILD_ID")" || return
  python3 "$SCRIPT_DIR/nexolab-protected-frontend.py" gateway --origin "$EXTERNAL_FRONTEND_ORIGIN" || return
  log "Protected frontend exact source/build and anonymous gateway denial verified"
}
