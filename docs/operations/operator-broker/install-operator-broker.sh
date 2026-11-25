#!/usr/bin/env bash
# NEXOLAB Operator Broker owner installation (#1758). Run as the owner (nexolab) with sudo:
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
# Install and uninstall roll back on any failed step.
set -Eeuo pipefail
umask 022

declare -A PIN=(
  [nexolab-operator-broker.py]=2d80814c834c138070b73319ad916d7427a382909ba064b27053af60d5525f1f
  [nexolab-operator-broker.service]=90c1f0974d6807a92ab2c8e4082583e17e54a677dba177a247b5a1c59a311109
  [nexolab-operator-broker.socket]=c1555f81c9de214e43d86230d5a67f9ac70b78f710d6f91985a8d0f4bd227e49
  [nexolab-storage-inventory.sh]=a8f4b9c96f1f98b6fafa72c1782cdfc6590d0640f0dcc04ee43c43ef93d1703b
)
LIB=/usr/local/lib/nexolab-operator
UNIT_DIR=/etc/systemd/system
DEV_UID=1001
DEV_GROUP=nexolab-dev

say() { printf '== %s\n' "$*"; }
INSTALLING=0
die() {
  printf 'OPERATOR_BROKER_INSTALL_FAILED %s\n' "$*"
  if [ "$INSTALLING" = 1 ]; then remove_installed; echo "rolled back: broker removed, production untouched"; fi
  exit 1
}
[ "$(id -u)" != 0 ] || die "run as the owner account with sudo available, not as root"
[ "$(id -u)" != "$DEV_UID" ] || die "the development account cannot install the broker"

client_call() { # client_call <as-user> <op>
  sudo -u "$1" python3 -I -c '
import json, socket, sys, time, uuid
req = {"v": 1, "op": sys.argv[1], "args": {}, "request_id": str(uuid.uuid4()), "ts": time.time()}
s = socket.socket(socket.AF_UNIX); s.settimeout(60); s.connect("/run/nexolab-operator/broker.sock")
s.sendall(json.dumps(req).encode() + b"\n"); s.shutdown(socket.SHUT_WR)
data = b""
while True:
    c = s.recv(65536)
    if not c: break
    data += c
r = json.loads(data); print(r.get("ok"), r.get("error"), (r.get("receipt") or {}).get("seq"))' "$2"
}

remove_installed() {
  sudo systemctl disable --now nexolab-operator-broker.socket >/dev/null 2>&1 || true
  sudo systemctl stop nexolab-operator-broker.service >/dev/null 2>&1 || true
  sudo rm -f "$UNIT_DIR/nexolab-operator-broker.socket" "$UNIT_DIR/nexolab-operator-broker.service"
  sudo rm -rf "$LIB"
  sudo systemctl daemon-reload
}

install() {
  local src="${1:?payload directory required}" stage name
  sudo -v || die "sudo"
  getent group "$DEV_GROUP" >/dev/null || die "group $DEV_GROUP missing"
  [ ! -e "$LIB" ] || die "$LIB already exists: run uninstall first (no in-place overwrite)"
  stage=$(sudo mktemp -d /root/nexolab-operator-stage.XXXXXX)
  trap 'sudo rm -rf "$stage"' EXIT
  say "copy payload into root-only staging and verify pins"
  for name in "${!PIN[@]}"; do
    sudo cat -- "$src/$name" | sudo tee "$stage/$name" >/dev/null || die "missing $name"
    echo "${PIN[$name]}  $stage/$name" | sudo sha256sum -c --quiet - || die "checksum mismatch $name"
  done
  say "preflight (no change)"
  python3 -I -c 'import ast,sys; ast.parse(open(sys.argv[1]).read())' <(sudo cat "$stage/nexolab-operator-broker.py") \
    || die "broker does not parse"
  if command -v systemd-analyze >/dev/null; then
    sudo systemd-analyze verify --man=no "$stage/nexolab-operator-broker.socket" "$stage/nexolab-operator-broker.service" \
      2>&1 | grep -vE 'is not executable|No such file|Neither a valid executable' || true
  fi
  [ ! -e "$UNIT_DIR/nexolab-operator-broker.service" ] || die "unit already present"

  say "install root-owned code and units"
  INSTALLING=1
  trap 'die "step failed (line $LINENO)"' ERR
  sudo install -d -o root -g root -m 0755 "$LIB" "$LIB/handlers"
  sudo install -o root -g root -m 0755 "$stage/nexolab-operator-broker.py" "$LIB/nexolab-operator-broker.py"
  sudo install -o root -g root -m 0755 "$stage/nexolab-storage-inventory.sh" "$LIB/handlers/nexolab-storage-inventory.sh"
  sudo install -o root -g root -m 0644 "$stage/nexolab-operator-broker.service" "$UNIT_DIR/nexolab-operator-broker.service"
  sudo install -o root -g root -m 0644 "$stage/nexolab-operator-broker.socket" "$UNIT_DIR/nexolab-operator-broker.socket"
  sudo install -d -o root -g root -m 0700 /etc/nexolab-operator /etc/nexolab-operator/approvals
  sudo install -d -o root -g "$DEV_GROUP" -m 0750 /var/log/nexolab-operator /var/lib/nexolab-operator \
    /var/lib/nexolab-operator/reports
  sudo systemctl daemon-reload
  sudo systemctl enable --now nexolab-operator-broker.socket

  say "acceptance"
  local denied allowed
  denied=$(client_call "$(id -un)" broker.list) || true
  echo "owner account (not allowed): $denied"
  [[ "$denied" == "False unauthorized_peer"* ]] || die "unauthorized peer was not rejected"
  allowed=$(client_call nexolab-dev broker.list) || true
  echo "development account: $allowed"
  [[ "$allowed" == "True None"* ]] || die "development account could not list operations"
  sudo python3 -I -B "$LIB/nexolab-operator-broker.py" verify-audit | grep -q '"ok": true' || die "audit chain"
  trap - ERR
  INSTALLING=0
  echo "OPERATOR_BROKER_INSTALLED socket=$(systemctl is-enabled nexolab-operator-broker.socket)/$(systemctl is-active nexolab-operator-broker.socket)"
}

status() {
  systemctl --no-pager status nexolab-operator-broker.socket nexolab-operator-broker.service 2>&1 | head -30 || true
  sudo python3 -I -B "$LIB/nexolab-operator-broker.py" verify-audit 2>&1 || true
}

uninstall() {
  sudo -v || die "sudo"
  remove_installed
  echo "OPERATOR_BROKER_REMOVED (audit log /var/log/nexolab-operator and reports kept as evidence)"
}

case "${1:-}" in
  install) install "${2:-}" ;;
  status) status ;;
  uninstall) uninstall ;;
  *) echo "usage: $0 install <payload-dir> | status | uninstall"; exit 64 ;;
esac
