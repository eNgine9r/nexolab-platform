#!/usr/bin/env bash
# NEXOLAB owner-run, READ-ONLY review of one workspace directory (#1710).
#
#   sudo bash nexolab-workspace-review.sh /home/nexolab/commander-workspaces/nexolab-platform/guarded-update-1313 [output-dir]
#
# Reports sizes, packages/archives, the largest files, Git state and every
# reference to the directory (systemd units, running processes, container
# mounts, deployment/recovery records, project state). It never deletes,
# moves, extracts or modifies anything and does not read secret contents.
set -u
umask 077

TARGET="${1:?usage: nexolab-workspace-review.sh <directory> [output-dir]}"
OUT_DIR="${2:-$PWD}"
OPERATOR="${NEXOLAB_OPERATOR:-nexolab}"
OPERATOR_HOME="${NEXOLAB_OPERATOR_HOME:-$(getent passwd "$OPERATOR" | cut -d: -f6)}"
SCAN_TIMEOUT="${NEXOLAB_REVIEW_SCAN_TIMEOUT:-900}"
[ -d "$TARGET" ] && [ ! -L "$TARGET" ] || { echo "Not a real directory: $TARGET" >&2; exit 1; }
TARGET="$(readlink -f "$TARGET")"
NAME="$(basename "$TARGET")"
REPORT="$OUT_DIR/nexolab-workspace-review-$NAME-$(date -u +%Y%m%dT%H%M%SZ).txt"

section() { printf '\n===== %s =====\n' "$*"; }
scan() { timeout "$SCAN_TIMEOUT" nice -n 19 ionice -c3 "$@"; }

{
  echo "Read-only workspace review of $TARGET ($(date -u +%Y-%m-%dT%H:%M:%SZ), $(hostname))"
  section "Size by subdirectory (depth 2)"
  scan du -xh --max-depth=2 "$TARGET" 2>/dev/null | sort -rh | head -40

  section "Packages and archives (size, modified, path)"
  scan find "$TARGET" -xdev -type f \( -name '*.tar' -o -name '*.tar.gz' -o -name '*.tgz' -o -name '*.tar.zst' \
      -o -name '*.zip' -o -name '*.deb' -o -name '*.img' -o -name '*.dump' -o -name '*.sql*' -o -name '*.sqlite*' \
      -o -name '*.age' -o -name '*.gpg' -o -name '*.enc' -o -name '*.sha256' -o -name '*manifest*.json' \) \
      -printf '%s\t%TY-%Tm-%Td\t%p\n' 2>/dev/null | sort -rn | head -80 | numfmt --field=1 --to=iec-i --suffix=B 2>/dev/null

  section "Largest 30 files"
  scan find "$TARGET" -xdev -type f -printf '%s\t%p\n' 2>/dev/null | sort -rn | head -30 | numfmt --field=1 --to=iec-i --suffix=B 2>/dev/null

  section "Possibly sensitive files (names only, contents not read)"
  scan find "$TARGET" -xdev -type f \( -name '.env*' -o -name '*.key' -o -name '*.pem' -o -name '*token*' -o -name '*secret*' \) -printf '%p\n' 2>/dev/null | head -40

  section "Git repositories inside (dirty / unpushed / stashes)"
  scan find "$TARGET" -xdev -maxdepth 4 -name .git -printf '%h\n' 2>/dev/null | while read -r repo; do
    dirty="$(runuser -u "$OPERATOR" -- git -C "$repo" status --porcelain 2>/dev/null | wc -l)"
    unpushed="$(runuser -u "$OPERATOR" -- git -C "$repo" rev-list --count '@{u}..HEAD' 2>/dev/null || echo no-upstream)"
    stashes="$(runuser -u "$OPERATOR" -- git -C "$repo" stash list 2>/dev/null | wc -l)"
    head="$(runuser -u "$OPERATOR" -- git -C "$repo" log -1 --format='%h %cs %s' 2>/dev/null | cut -c1-100)"
    printf '%s\tdirty=%s unpushed=%s stashes=%s head=%s\n' "$repo" "$dirty" "$unpushed" "$stashes" "$head"
  done

  section "References: systemd units"
  grep -rlsF "$TARGET" /etc/systemd/system /run/systemd/system "$OPERATOR_HOME/.config/systemd" 2>/dev/null || echo "none"

  section "References: running processes (cwd/exe inside)"
  found=0
  for pid in $(ls /proc | grep -E '^[0-9]+$'); do
    for link in cwd exe; do
      path="$(readlink "/proc/$pid/$link" 2>/dev/null)" || continue
      case "$path" in "$TARGET"|"$TARGET"/*) echo "$pid $link $path"; found=1 ;; esac
    done
  done
  [ "$found" = 1 ] || echo "none"

  section "References: container mounts and image sources"
  if command -v docker >/dev/null 2>&1; then
    docker ps -aq | xargs -r docker inspect --format '{{.Name}} {{range .Mounts}}{{.Source}} {{end}}' 2>/dev/null | grep -F "$TARGET" || echo "none"
  fi

  section "References: deployment, recovery, backup records and project state (file list)"
  for root in "$OPERATOR_HOME/nexolab-platform/runtime" "$OPERATOR_HOME/nexolab-platform/.project" /var/backups/nexolab /etc/nexolab; do
    [ -d "$root" ] || continue
    scan grep -rlsF --include='*.json' --include='*.txt' --include='*.env' --include='*.md' --include='*.log' \
      --include='*.sha256' --include='*.manifest' -e "$TARGET" -e "$NAME" "$root" 2>/dev/null | head -40
  done
} >"$REPORT" 2>&1

echo "Read-only review written to $REPORT"
