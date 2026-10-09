#!/bin/sh
# Execute inside the PostgreSQL container, so limits cover the actual client.
set -eu

bounded_integer() {
  case "$2" in ''|*[!0-9]*) echo "Invalid backup limit: $1" >&2; exit 78 ;; esac
  # Bound the decimal length before arithmetic; never accept unlimited/zero limits.
  [ "${#2}" -le 6 ] && [ "$2" -ge "$3" ] && [ "$2" -le "$4" ] || {
    echo "Backup limit outside policy: $1" >&2; exit 78;
  }
}

memory_kib=${NEXOLAB_BACKUP_CLIENT_MEMORY_KIB:-524288}
cpu_seconds=${NEXOLAB_BACKUP_CLIENT_CPU_SECONDS:-600}
wall_seconds=${NEXOLAB_BACKUP_CLIENT_TIMEOUT_SECONDS:-900}
bounded_integer memory_kib "$memory_kib" 65536 524288
bounded_integer cpu_seconds "$cpu_seconds" 1 600
bounded_integer wall_seconds "$wall_seconds" 1 900
case "${1:-}" in
  dump) program=pg_dump; duration=$wall_seconds ;;
  list) program=pg_restore; duration=60 ;;
  *) echo 'Backup client mode must be dump or list' >&2; exit 78 ;;
esac
for tool in nice ionice timeout "$program"; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "Required bounded backup client tool missing: $tool" >&2; exit 78;
  }
done
ulimit -v "$memory_kib" || exit 78
ulimit -t "$cpu_seconds" || exit 78
printf 'PostgreSQL client guard: mode=%s memory_kib=%s cpu_seconds=%s wall_seconds=%s\n' \
  "$1" "$memory_kib" "$cpu_seconds" "$duration" >&2

if [ "$1" = dump ]; then
  export PGCONNECT_TIMEOUT=10
  export PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=900000 -c lock_timeout=15000'
  exec nice -n 10 ionice -c 3 timeout -k 10 "$duration" \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -Z 3 --lock-wait-timeout=15000
fi
exec nice -n 10 ionice -c 3 timeout -k 10 "$duration" pg_restore --list
