#!/usr/bin/env bash
set -Eeuo pipefail

for candidate in google-chrome google-chrome-stable chromium chromium-browser; do
  if browser_path="$(command -v "$candidate" 2>/dev/null)" && [[ -n "$browser_path" && -x "$browser_path" ]]; then
    printf '%s\n' "$browser_path"
    exit 0
  fi
done

printf 'No supported preinstalled Chrome/Chromium executable was found on PATH.\n' >&2
exit 1
