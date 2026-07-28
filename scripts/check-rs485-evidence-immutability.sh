#!/usr/bin/env bash
set -Eeuo pipefail

BASE_REF="${1:-}"

if [[ -z "$BASE_REF" ]]; then
  printf 'Usage: %s <base-ref>\n' "$0" >&2
  exit 2
fi

if ! git rev-parse --verify --quiet "$BASE_REF^{commit}" >/dev/null; then
  printf 'RS-485 evidence immutability check: base ref not found: %s\n' "$BASE_REF" >&2
  exit 2
fi

violations=0
while IFS=$'\t' read -r status path extra_path; do
  [[ -z "$status" ]] && continue

  case "$status" in
    A)
      if [[ ! "$path" =~ ^evidence/rs485/[0-9]{4}/[0-9]{2}/[0-9]{2}/[A-Za-z0-9._-]+/[a-z0-9][a-z0-9._-]{7,127}\.json$ ]]; then
        printf 'Invalid new RS-485 evidence archive path: %s\n' "$path" >&2
        violations=1
      fi
      ;;
    *)
      printf 'RS-485 raw evidence is append-only; %s is not allowed for %s' "$status" "$path" >&2
      if [[ -n "${extra_path:-}" ]]; then
        printf ' -> %s' "$extra_path" >&2
      fi
      printf '\n' >&2
      violations=1
      ;;
  esac
done < <(git diff --name-status --find-renames "$BASE_REF"...HEAD -- evidence/rs485 ':(exclude)evidence/rs485/.gitkeep')

if [[ "$violations" -ne 0 ]]; then
  exit 1
fi

printf 'RS-485 evidence immutability policy passed against %s\n' "$BASE_REF"
