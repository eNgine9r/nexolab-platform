#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
REF="${1:-HEAD}"
TARGET_DIR="${2:-}"

if [[ -z "$TARGET_DIR" ]]; then
  printf 'Usage: %s [ref] <target-directory>\n' "$0" >&2
  exit 2
fi

SHA="$(git -C "$ROOT_DIR" rev-parse --verify "${REF}^{commit}")"
if [[ -e "$TARGET_DIR" ]]; then
  printf 'Target already exists: %s\n' "$TARGET_DIR" >&2
  exit 2
fi

git -C "$ROOT_DIR" worktree add --detach "$TARGET_DIR" "$SHA"
status="$(git -C "$TARGET_DIR" status --porcelain)"
if [[ -n "$status" ]]; then
  printf 'Fresh verification worktree is not clean:\n%s\n' "$status" >&2
  git -C "$ROOT_DIR" worktree remove --force "$TARGET_DIR" || true
  exit 1
fi

printf 'Prepared clean verification worktree at %s for %s\n' "$TARGET_DIR" "$SHA"
printf 'Remove after verification with: git -C %q worktree remove %q\n' "$ROOT_DIR" "$TARGET_DIR"
