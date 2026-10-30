#!/usr/bin/env bash
# NEXOLAB #1428: one-time bounded PostgreSQL backup. No Docker/network changes.
# This is a PARTIAL state backup, NOT a complete disaster-recovery receipt.
set -Eeuo pipefail
umask 077
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

fail() { printf 'BLOCKED: %s\n' "$*" >&2; exit 78; }
(( EUID == 0 )) || fail "root required"
[[ $# == 0 || ( $# == 1 && $1 == "--check" ) ]] || fail "usage: [--check]"
backup_dir=/var/backups/nexolab
[[ -d "$backup_dir" && ! -L "$backup_dir" ]] || fail "protected backup directory missing or symlink"
[[ $(stat -c %u -- "$backup_dir") == 0 ]] || fail "backup directory must be root-owned"
dir_mode=$(stat -c %a -- "$backup_dir")
(( (8#$dir_mode & 0022) == 0 )) || fail "backup directory permits untrusted writes"
[[ $(stat -c %d -- "$backup_dir") == $(stat -c %d -- /) ]] || fail "backup directory is on a different filesystem; inspect capacity explicitly"

max_bytes=$((4 * 1024 * 1024 * 1024))
reserve_bytes=$((20 * 1024 * 1024 * 1024))
available=$(df -B1 --output=avail "$backup_dir" | tail -1 | tr -d ' ')
[[ "$available" =~ ^[0-9]+$ ]] || fail "filesystem free space unknown"
(( available >= max_bytes + reserve_bytes )) || fail "must reserve 20 GiB plus at most 4 GiB new archive"

container=nexolab-central-postgres-1
[[ $(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null) == true ]] || fail "PostgreSQL container not running"
identity=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}/{{index .Config.Labels "com.docker.compose.service"}}' "$container" 2>/dev/null) || fail "Compose identity unknown"
[[ "$identity" == nexolab-central/postgres ]] || fail "not the accepted central PostgreSQL service"
if [[ ${1:-} == "--check" ]]; then
  printf 'PG_BACKUP_PREFLIGHT=PASS\nPG_BACKUP_PERFORMED=NO\n'
  exit 0
fi

name="pg-incident-$(date -u +%Y%m%dT%H%M%SZ).dump"
final="$backup_dir/$name"
partial="$final.partial"
[[ ! -e "$final" && ! -e "$partial" && ! -L "$final" && ! -L "$partial" ]] || fail "archive already exists"
cleanup() { rm -f -- "$partial"; }
trap cleanup EXIT

# Bounded, low-priority, read-only PostgreSQL client. No service restart.
# Pipefail plus iflag=fullblock prevents accepting a truncated 4 GiB stream.
timeout -k 10 930 docker exec "$container" sh -ec '
  set -eu
  ulimit -v 524288
  ulimit -t 600
  export PGCONNECT_TIMEOUT=10
  export PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=900000 -c lock_timeout=15000"
  exec nice -n 10 ionice -c 3 timeout -k 10 900 pg_dump \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -Z 3 --lock-wait-timeout=15000
' | dd of="$partial" bs=1M count=4096 iflag=fullblock status=none

bytes=$(stat -c %s -- "$partial")
(( bytes > 0 && bytes < max_bytes )) || fail "archive empty or at configured size ceiling"
available=$(df -B1 --output=avail "$backup_dir" | tail -1 | tr -d ' ')
[[ "$available" =~ ^[0-9]+$ ]] && (( available >= reserve_bytes )) || fail "post-backup disk reserve violated"

# Archive TOC verification is NOT a fresh-volume restore.
docker exec -i "$container" sh -ec \
  'timeout -k 10 60 pg_restore --list >/dev/null' < "$partial"
chmod 0600 "$partial"
mv -n -- "$partial" "$final"
[[ -f "$final" && ! -e "$partial" ]] || fail "archive finalization failed"
trap - EXIT
printf 'PG_BACKUP_ARCHIVE=CREATED\nPG_RESTORE_TOC=PASS\nPG_RESTORE_ACTUAL=NOT_PERFORMED\n'
printf 'PG_BACKUP_BYTES=%s\n' "$bytes"
sha256sum -- "$final"
df -h "$backup_dir"
