#!/usr/bin/env bash
# NEXOLAB Operator Broker owner installation (#1758, #1769). Run as the owner (nexolab) with sudo:
#
#   bash install-operator-broker.sh install   <payload-dir>
#   bash install-operator-broker.sh upgrade   <payload-dir>   (verify new pins, snapshot, replace;
#                                                            any failure restores the previous version)
#   bash install-operator-broker.sh rollback                  (back to the version retained by the last upgrade)
#   bash install-operator-broker.sh status
#   bash install-operator-broker.sh uninstall
#
# <payload-dir> holds the six pinned payload files below (a reviewed copy of main). Every
# file is first copied into a root-only staging directory and verified there, so nothing
# the development account can still modify is ever installed. The broker is
# socket-activated, touches no production service, container, network or credential at
# install time, and keeps the audit log and reports on uninstall (evidence).
#
# Acceptance proves the three trust boundaries on the real socket:
#   owner (not in the socket group)  -> refused by the kernel at the socket file (EACCES)
#                                       (or by the broker, if the owner is in the group)
#   root                             -> refused by the broker (unauthorized_peer)
#   development account, inside a transient unit with the dev-session sandbox
#   (NoNewPrivileges, ProtectSystem=strict, PrivateDevices, no Docker socket) -> allowed
# Any failed step removes everything installed and verifies the removal.
set -Eeuo pipefail
umask 022

declare -A PIN=(
  [nexolab-operator-broker.py]=01a4275d6fc07b7ce4aa55b10ffaab2be512e22cf56b71ab40f3193b58c1a6c4
  [nexolab-operator-broker.service]=9dd3659153a46a5f1c8877bb21a9ceffc22f8e0e0f0bb3ae29b48e93a9a601bd
  [nexolab-operator-broker.socket]=c1555f81c9de214e43d86230d5a67f9ac70b78f710d6f91985a8d0f4bd227e49
  [nexolab-storage-inventory.sh]=a8f4b9c96f1f98b6fafa72c1782cdfc6590d0640f0dcc04ee43c43ef93d1703b
  [wp2c-stage3-backend.py]=b3176baff391b104dd71c876d9b2aef97bf871954aa3fbf4bb082f45fe5acac4
  [wp2c-stage2-frontend.py]=bcbb9788a36ba717e43d8717ea790714f147b87bb77af995cc64a29acd3086cb
)
LIB=/usr/local/lib/nexolab-operator
UNIT_DIR=/etc/systemd/system
SOCK=/run/nexolab-operator/broker.sock
DEV_UID=1001                                   # fixed in the pinned unit (NEXOLAB_OPERATOR_ALLOWED_UIDS)
DEV_USER="${NEXOLAB_OPERATOR_DEV_USER:-nexolab-dev}"  # CI runners name uid 1001 differently
DEV_GROUP=nexolab-dev                          # fixed in the pinned socket unit
DEPLOY_USER=nexolab                            # fixed in the pinned unit (NEXOLAB_OPERATOR_DEPLOY_USER)
DEPLOY_DIR=/var/lib/nexolab-operator-deploy
PREV=/var/lib/nexolab-operator/previous        # one retained previous version (root-only, SHA-256 manifest)
STAGE=""
INSTALLING=0
RESTORE_FROM=""                                # set during upgrade/rollback: the version to restore on failure

say() { printf '== %s\n' "$*"; }
cleanup_stage() { if [ -n "${STAGE:-}" ]; then sudo rm -rf -- "$STAGE"; STAGE=""; fi; }
trap cleanup_stage EXIT

installed_leftovers() {
  local path
  for path in "$LIB" "$UNIT_DIR/nexolab-operator-broker.socket" "$UNIT_DIR/nexolab-operator-broker.service"; do
    sudo test -e "$path" && echo "$path"
  done
  systemctl is-active --quiet nexolab-operator-broker.socket && echo "socket active"
  systemctl is-active --quiet nexolab-operator-broker.service && echo "service active"
  sudo test -S "$SOCK" && echo "$SOCK"
  return 0
}

remove_installed() {
  sudo systemctl disable --now nexolab-operator-broker.socket >/dev/null 2>&1 || true
  sudo systemctl stop nexolab-operator-broker.service >/dev/null 2>&1 || true
  sudo rm -f "$UNIT_DIR/nexolab-operator-broker.socket" "$UNIT_DIR/nexolab-operator-broker.service"
  sudo rm -rf "$LIB"
  sudo systemctl daemon-reload
  sudo systemctl reset-failed nexolab-operator-broker.socket nexolab-operator-broker.service >/dev/null 2>&1 || true
}

verify_removed() { # prints the marker; returns non-zero if anything is left
  local left
  left="$(installed_leftovers)"
  if [ -z "$left" ]; then echo "ROLLBACK_VERIFIED broker fully removed, production untouched"; return 0; fi
  echo "HARD_BLOCKER_ROLLBACK_INCOMPLETE left: $(echo "$left" | tr '\n' ' ')"
  return 1
}

installed_version() {
  sudo sed -n 's/^VERSION = "\([0-9.]*\)"$/\1/p' "$LIB/nexolab-operator-broker.py" 2>/dev/null | head -1
}

# snapshot_to <dir>: copy the installed code and units with a SHA-256 manifest (root-only).
snapshot_to() {
  local dir="$1"
  sudo rm -rf -- "$dir"
  sudo install -d -o root -g root -m 0700 "$dir" "$dir/lib" "$dir/units" || return 1
  sudo cp -a -- "$LIB/." "$dir/lib/" || return 1
  sudo cp -a -- "$UNIT_DIR/nexolab-operator-broker.service" "$UNIT_DIR/nexolab-operator-broker.socket" "$dir/units/" \
    || return 1
  sudo sh -c 'cd "$1" && find lib units -type f -print0 | sort -z | xargs -0 sha256sum > MANIFEST.sha256' sh "$dir" \
    || return 1
  installed_version | sudo tee "$dir/VERSION" >/dev/null
}

# restore_from <dir>: verify the manifest, reinstall that version exactly and accept it on the real socket.
# Never calls die (it runs inside die); returns non-zero on any failure.
restore_from() {
  local dir="$1"
  sudo test -s "$dir/MANIFEST.sha256" || { echo "no snapshot manifest in $dir"; return 1; }
  sudo sh -c 'cd "$1" && sha256sum -c --quiet MANIFEST.sha256' sh "$dir" || { echo "snapshot manifest mismatch"; return 1; }
  remove_installed
  sudo install -d -o root -g root -m 0755 "$LIB" || return 1
  sudo cp -a -- "$dir/lib/." "$LIB/" || return 1
  sudo chown -R root:root "$LIB" || return 1
  sudo install -o root -g root -m 0644 "$dir/units/nexolab-operator-broker.service" "$dir/units/nexolab-operator-broker.socket" \
    "$UNIT_DIR/" || return 1
  sudo systemctl daemon-reload || return 1
  sudo systemctl enable --now nexolab-operator-broker.socket || return 1
  acceptance
}

die() {
  trap - ERR
  printf 'OPERATOR_BROKER_INSTALL_FAILED %s\n' "$*"
  if [ "$INSTALLING" = 1 ]; then
    INSTALLING=0
    if [ -n "$RESTORE_FROM" ]; then
      say "restoring the previous broker version (automatic rollback)"
      if restore_from "$RESTORE_FROM"; then
        echo "OPERATOR_BROKER_UPGRADE_ROLLED_BACK version=$(installed_version) (previous version restored and accepted)"
        exit 3
      fi
      echo "previous version could not be restored; removing the broker instead"
    fi
    remove_installed
    verify_removed || exit 2
  fi
  exit 1
}

[ "$(id -u)" != 0 ] || die "run as the owner account with sudo available, not as root"
[ "$(id -u)" != "$DEV_UID" ] || die "the development account cannot install the broker"

# Never fails (an ERR trap inside a command substitution must not trigger a rollback).
# client <how> <op>: prints "<ok> <error> <seq>" or "DENIED_FS <errno-name>" when the kernel
# refuses the socket file itself. <how> is "owner", "root" or "dev".
CLIENT='
import errno, json, socket, sys, time, uuid
req = {"v": 1, "op": sys.argv[1], "args": {}, "request_id": str(uuid.uuid4()), "ts": time.time()}
s = socket.socket(socket.AF_UNIX); s.settimeout(60)
try:
    s.connect(sys.argv[2])
except PermissionError as exc:
    print("DENIED_FS", errno.errorcode.get(exc.errno, exc.errno)); raise SystemExit(0)
s.sendall(json.dumps(req).encode() + b"\n"); s.shutdown(socket.SHUT_WR)
data = b""
while True:
    c = s.recv(65536)
    if not c: break
    data += c
r = json.loads(data); print(r.get("ok"), r.get("error"), (r.get("receipt") or {}).get("seq"))'
client() {
  case "$1" in
    owner) python3 -I -c "$CLIENT" "$2" "$SOCK" || echo "CLIENT_ERROR" ;;
    root) sudo python3 -I -c "$CLIENT" "$2" "$SOCK" || echo "CLIENT_ERROR" ;;
    dev) # same sandbox properties as nexolab-dev-session.service (#1706)
      sudo systemd-run --quiet --wait --pipe --collect --uid="$DEV_USER" \
        -p NoNewPrivileges=yes -p PrivateDevices=yes -p PrivateTmp=yes -p ProtectSystem=strict \
        -p UMask=0077 -p "InaccessiblePaths=-/home/nexolab -/etc/nexolab -/var/lib/nexolab -/var/lib/docker -/run/docker.sock -/run/containerd/containerd.sock" \
        /usr/bin/python3 -I -c "$CLIENT" "$2" "$SOCK" || echo "CLIENT_ERROR" ;;
  esac
}

install() {
  local src="${1:?payload directory required}" name
  sudo -v || die "sudo"
  getent group "$DEV_GROUP" >/dev/null || die "group $DEV_GROUP missing"
  [ "$(id -u "$DEV_USER" 2>/dev/null)" = "$DEV_UID" ] || die "$DEV_USER is not uid $DEV_UID (pinned in the unit)"
  id -nG "$DEV_USER" | tr ' ' '\n' | grep -qx "$DEV_GROUP" || die "$DEV_USER is not in group $DEV_GROUP"
  [ ! -e "$LIB" ] || die "$LIB already exists: run uninstall first (no in-place overwrite)"
  [ ! -e "$UNIT_DIR/nexolab-operator-broker.service" ] || die "unit already present: run uninstall first"
  STAGE=$(sudo mktemp -d /root/nexolab-operator-stage.XXXXXX) || die "staging"
  say "copy payload into root-only staging and verify pins"
  for name in "${!PIN[@]}"; do
    sudo cat -- "$src/$name" | sudo tee "$STAGE/$name" >/dev/null || die "missing $name"
    echo "${PIN[$name]}  $STAGE/$name" | sudo sha256sum -c --quiet - || die "checksum mismatch $name"
  done
  say "preflight (no change)"
  sudo python3 -I -c 'import ast,sys; ast.parse(open(sys.argv[1]).read())' "$STAGE/nexolab-operator-broker.py" \
    || die "broker does not parse"
  if command -v systemd-analyze >/dev/null; then
    sudo systemd-analyze verify --man=no "$STAGE/nexolab-operator-broker.socket" "$STAGE/nexolab-operator-broker.service" \
      2>&1 | grep -vE 'is not executable|No such file|Neither a valid executable' || true
  fi

  say "install root-owned code and units"
  INSTALLING=1
  trap 'die "step failed (line $LINENO)"' ERR
  sudo install -d -o root -g root -m 0755 "$LIB" "$LIB/handlers"
  sudo install -o root -g root -m 0755 "$STAGE/nexolab-operator-broker.py" "$LIB/nexolab-operator-broker.py"
  sudo install -o root -g root -m 0755 "$STAGE/nexolab-storage-inventory.sh" "$LIB/handlers/nexolab-storage-inventory.sh"
  sudo install -o root -g root -m 0755 "$STAGE/wp2c-stage2-frontend.py" "$LIB/handlers/wp2c-stage2-frontend.py"
  sudo install -o root -g root -m 0755 "$STAGE/wp2c-stage3-backend.py" "$LIB/handlers/wp2c-stage3-backend.py"
  sudo install -o root -g root -m 0644 "$STAGE/nexolab-operator-broker.service" "$UNIT_DIR/nexolab-operator-broker.service"
  sudo install -o root -g root -m 0644 "$STAGE/nexolab-operator-broker.socket" "$UNIT_DIR/nexolab-operator-broker.socket"
  sudo install -d -o root -g root -m 0700 /etc/nexolab-operator /etc/nexolab-operator/approvals
  # Audit receipts are readable by the dev group (setgid keeps the group); raw reports are root-only.
  sudo install -d -o root -g "$DEV_GROUP" -m 2750 /var/log/nexolab-operator
  sudo install -d -o root -g root -m 0700 /var/lib/nexolab-operator /var/lib/nexolab-operator/reports
  # Verified deployment artifacts are readable by the owner account only (deploy.lan-frontend).
  if getent passwd "$DEPLOY_USER" >/dev/null; then
    sudo install -d -o root -g "$(id -gn "$DEPLOY_USER")" -m 0750 "$DEPLOY_DIR"
  fi
  cleanup_stage
  sudo systemctl daemon-reload
  sudo systemctl enable --now nexolab-operator-broker.socket

  acceptance || die "acceptance failed"
  [ "${NEXOLAB_OPERATOR_TEST_FAULT:-}" != after-install ] || die "injected test fault (after-install)"
  trap - ERR
  INSTALLING=0
  echo "OPERATOR_BROKER_INSTALLED socket=enabled/active owner=refused root=refused dev=allowed audit=ok"
}

# acceptance: the three trust boundaries on the real socket plus the fail-closed final state.
# Returns non-zero (never dies) so it also serves restore_from inside die.
acceptance() {
  say "acceptance on the real socket"
  local owner root dev
  owner=$(client owner broker.list 2>&1) || true
  echo "owner $(id -un) (uid $(id -u)): $owner"
  if id -nG | tr ' ' '\n' | grep -qx "$DEV_GROUP"; then
    [[ "$owner" == "False unauthorized_peer"* ]] || { echo "ACCEPTANCE: owner in $DEV_GROUP was not rejected by the broker"; return 1; }
  else
    [[ "$owner" == "DENIED_FS EACCES" ]] || { echo "ACCEPTANCE: owner outside $DEV_GROUP was not refused at the socket file"; return 1; }
  fi
  root=$(client root broker.list 2>&1) || true
  echo "root: $root"
  [[ "$root" == "False unauthorized_peer"* ]] || { echo "ACCEPTANCE: root peer was not rejected by the broker"; return 1; }
  dev=$(client dev broker.list 2>&1) || true
  echo "$DEV_USER (uid $DEV_UID, dev-session sandbox): $dev"
  [[ "$dev" == "True None"* ]] || { echo "ACCEPTANCE: development account could not list operations from its sandbox"; return 1; }
  dev=$(client dev system.summary 2>&1) || true
  echo "$DEV_USER system.summary: $dev"
  [[ "$dev" == "True None"* ]] || { echo "ACCEPTANCE: development account read-only diagnostic failed"; return 1; }
  sudo python3 -I -B "$LIB/nexolab-operator-broker.py" verify-audit | grep -q '"ok": true' || { echo "ACCEPTANCE: audit chain"; return 1; }

  say "final state (fail closed)"
  [ "$(systemctl is-enabled nexolab-operator-broker.socket)" = enabled ] || { echo "ACCEPTANCE: socket not enabled"; return 1; }
  [ "$(systemctl is-active nexolab-operator-broker.socket)" = active ] || { echo "ACCEPTANCE: socket not active"; return 1; }
  [ "$(sudo stat -c '%U:%G %a' "$SOCK")" = "root:$DEV_GROUP 660" ] || { echo "ACCEPTANCE: socket ownership/mode"; return 1; }
  [ "$(sudo stat -c '%U:%G %a' "$LIB/nexolab-operator-broker.py")" = "root:root 755" ] || { echo "ACCEPTANCE: broker file ownership/mode"; return 1; }
  [ "$(systemctl show -p NoNewPrivileges --value nexolab-operator-broker.service)" = yes ] || { echo "ACCEPTANCE: service sandbox"; return 1; }
  echo "ACCEPTANCE_OK version=$(installed_version)"
}

status() {
  systemctl --no-pager status nexolab-operator-broker.socket nexolab-operator-broker.service 2>&1 | head -30 || true
  sudo python3 -I -B "$LIB/nexolab-operator-broker.py" verify-audit 2>&1 || true
}

upgrade() {
  local src="${1:?payload directory required}" name check
  sudo -v || die "sudo"
  # Verify the NEW payload before touching the running broker: a bad payload changes nothing.
  check=$(sudo mktemp -d /root/nexolab-operator-check.XXXXXX) || die "staging"
  for name in "${!PIN[@]}"; do
    if ! sudo cat -- "$src/$name" | sudo tee "$check/$name" >/dev/null \
      || ! echo "${PIN[$name]}  $check/$name" | sudo sha256sum -c --quiet -; then
      sudo rm -rf -- "$check"; die "new payload invalid ($name); installed broker left unchanged"
    fi
  done
  sudo rm -rf -- "$check"
  if ! sudo test -e "$LIB/nexolab-operator-broker.py"; then
    say "new payload verified; no installed broker, plain install"
    install "$src"
    return
  fi
  local from
  from=$(installed_version)
  say "new payload verified; snapshot of the installed version ${from:-unknown}"
  snapshot_to "$PREV.pending" || die "could not snapshot the installed broker; installed broker left unchanged"
  # From here on any failure (even a payload changed after the check) restores the snapshot.
  RESTORE_FROM="$PREV.pending"
  INSTALLING=1
  trap 'die "step failed (line $LINENO)"' ERR
  say "replacing the installed broker (audit log kept)"
  remove_installed
  install "$src"
  RESTORE_FROM=""
  sudo rm -rf -- "$PREV"
  sudo mv -- "$PREV.pending" "$PREV"
  echo "OPERATOR_BROKER_UPGRADED from=${from:-unknown} to=$(installed_version) previous_retained=$PREV (undo: $0 rollback)"
}

rollback() {
  sudo -v || die "sudo"
  sudo test -s "$PREV/MANIFEST.sha256" || die "no retained previous version in $PREV"
  local from target
  from=$(installed_version)
  target=$(sudo cat "$PREV/VERSION" 2>/dev/null)
  say "rolling back ${from:-<none>} -> ${target:-unknown}"
  if sudo test -e "$LIB/nexolab-operator-broker.py"; then
    snapshot_to "$PREV.current" || die "could not snapshot the installed broker; nothing changed"
    RESTORE_FROM="$PREV.current"
  fi
  INSTALLING=1
  trap 'die "step failed (line $LINENO)"' ERR
  restore_from "$PREV" || die "the previous version failed its acceptance"
  INSTALLING=0
  trap - ERR
  if [ -n "$RESTORE_FROM" ]; then   # keep the replaced version so a second rollback rolls forward again
    RESTORE_FROM=""
    sudo rm -rf -- "$PREV"
    sudo mv -- "$PREV.current" "$PREV"
  fi
  echo "OPERATOR_BROKER_ROLLED_BACK from=${from:-none} to=$(installed_version)"
}

uninstall() {
  sudo -v || die "sudo"
  remove_installed
  verify_removed || exit 2
  echo "OPERATOR_BROKER_REMOVED (audit log /var/log/nexolab-operator and reports kept as evidence)"
}

case "${1:-}" in
  install) install "${2:-}" ;;
  upgrade) upgrade "${2:-}" ;;
  rollback) rollback ;;
  status) status ;;
  uninstall) uninstall ;;
  *) echo "usage: $0 install <payload-dir> | upgrade <payload-dir> | rollback | status | uninstall"; exit 64 ;;
esac
