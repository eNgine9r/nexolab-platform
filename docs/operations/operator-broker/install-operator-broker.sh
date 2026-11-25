#!/usr/bin/env bash
# NEXOLAB Operator Broker owner installation (#1758, #1769). Run as the owner (nexolab) with sudo:
#
#   bash install-operator-broker.sh install   <payload-dir>
#   bash install-operator-broker.sh status
#   bash install-operator-broker.sh uninstall
#
# <payload-dir> holds the four pinned payload files below (a reviewed copy of main). Every
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
  [nexolab-operator-broker.py]=0fd74afcfb6531addcbaadbf190748e0396857a995b6946647a790b582cccde0
  [nexolab-operator-broker.service]=90c1f0974d6807a92ab2c8e4082583e17e54a677dba177a247b5a1c59a311109
  [nexolab-operator-broker.socket]=c1555f81c9de214e43d86230d5a67f9ac70b78f710d6f91985a8d0f4bd227e49
  [nexolab-storage-inventory.sh]=a8f4b9c96f1f98b6fafa72c1782cdfc6590d0640f0dcc04ee43c43ef93d1703b
)
LIB=/usr/local/lib/nexolab-operator
UNIT_DIR=/etc/systemd/system
SOCK=/run/nexolab-operator/broker.sock
DEV_UID=1001                                   # fixed in the pinned unit (NEXOLAB_OPERATOR_ALLOWED_UIDS)
DEV_USER="${NEXOLAB_OPERATOR_DEV_USER:-nexolab-dev}"  # CI runners name uid 1001 differently
DEV_GROUP=nexolab-dev                          # fixed in the pinned socket unit
STAGE=""
INSTALLING=0

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

die() {
  trap - ERR
  printf 'OPERATOR_BROKER_INSTALL_FAILED %s\n' "$*"
  if [ "$INSTALLING" = 1 ]; then
    INSTALLING=0
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
  sudo install -o root -g root -m 0644 "$STAGE/nexolab-operator-broker.service" "$UNIT_DIR/nexolab-operator-broker.service"
  sudo install -o root -g root -m 0644 "$STAGE/nexolab-operator-broker.socket" "$UNIT_DIR/nexolab-operator-broker.socket"
  sudo install -d -o root -g root -m 0700 /etc/nexolab-operator /etc/nexolab-operator/approvals
  # Audit receipts are readable by the dev group (setgid keeps the group); raw reports are root-only.
  sudo install -d -o root -g "$DEV_GROUP" -m 2750 /var/log/nexolab-operator
  sudo install -d -o root -g root -m 0700 /var/lib/nexolab-operator /var/lib/nexolab-operator/reports
  cleanup_stage
  sudo systemctl daemon-reload
  sudo systemctl enable --now nexolab-operator-broker.socket

  say "acceptance on the real socket"
  local owner root dev
  owner=$(client owner broker.list 2>&1) || true
  echo "owner $(id -un) (uid $(id -u)): $owner"
  if id -nG | tr ' ' '\n' | grep -qx "$DEV_GROUP"; then
    [[ "$owner" == "False unauthorized_peer"* ]] || die "owner in $DEV_GROUP was not rejected by the broker"
  else
    [[ "$owner" == "DENIED_FS EACCES" ]] || die "owner outside $DEV_GROUP was not refused at the socket file"
  fi
  root=$(client root broker.list 2>&1) || true
  echo "root: $root"
  [[ "$root" == "False unauthorized_peer"* ]] || die "root peer was not rejected by the broker"
  dev=$(client dev broker.list 2>&1) || true
  echo "$DEV_USER (uid $DEV_UID, dev-session sandbox): $dev"
  [[ "$dev" == "True None"* ]] || die "development account could not list operations from its sandbox"
  dev=$(client dev system.summary 2>&1) || true
  echo "$DEV_USER system.summary: $dev"
  [[ "$dev" == "True None"* ]] || die "development account read-only diagnostic failed"
  sudo python3 -I -B "$LIB/nexolab-operator-broker.py" verify-audit | grep -q '"ok": true' || die "audit chain"

  say "final state (fail closed)"
  [ "$(systemctl is-enabled nexolab-operator-broker.socket)" = enabled ] || die "socket not enabled"
  [ "$(systemctl is-active nexolab-operator-broker.socket)" = active ] || die "socket not active"
  [ "$(sudo stat -c '%U:%G %a' "$SOCK")" = "root:$DEV_GROUP 660" ] || die "socket ownership/mode"
  [ "$(sudo stat -c '%U:%G %a' "$LIB/nexolab-operator-broker.py")" = "root:root 755" ] || die "broker file ownership/mode"
  [ "$(systemctl show -p NoNewPrivileges --value nexolab-operator-broker.service)" = yes ] || die "service sandbox"
  trap - ERR
  INSTALLING=0
  echo "OPERATOR_BROKER_INSTALLED socket=enabled/active owner=refused root=refused dev=allowed audit=ok"
}

status() {
  systemctl --no-pager status nexolab-operator-broker.socket nexolab-operator-broker.service 2>&1 | head -30 || true
  sudo python3 -I -B "$LIB/nexolab-operator-broker.py" verify-audit 2>&1 || true
}

uninstall() {
  sudo -v || die "sudo"
  remove_installed
  verify_removed || exit 2
  echo "OPERATOR_BROKER_REMOVED (audit log /var/log/nexolab-operator and reports kept as evidence)"
}

case "${1:-}" in
  install) install "${2:-}" ;;
  status) status ;;
  uninstall) uninstall ;;
  *) echo "usage: $0 install <payload-dir> | status | uninstall"; exit 64 ;;
esac
