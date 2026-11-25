#!/bin/sh
# GIT_ASKPASS helper for nexolab-gitlab-sync (#1713).
# Owner-installed to /usr/local/lib/nexolab-gitlab-sync/ (root-owned, 0755).
# Answers only prompts for the configured destination host, and only from the
# systemd credential (LoadCredential=gitlab-token). Never echoes the prompt,
# never logs, never answers prompts for any other host (e.g. GitHub).
set -eu

prompt="${1:-}"
host="${NEXOLAB_SYNC_DEST_HOST:-}"
token_file="${CREDENTIALS_DIRECTORY:-}/gitlab-token"

[ -n "$host" ] || exit 1

# Git prompts look like: Password for 'https://user@gitlab.example.invalid': — the host must match exactly.
case "$prompt" in
  *"'"*"'"*) ;;
  *) exit 1 ;;
esac
url="${prompt#*\'}"
url="${url%%\'*}"
case "$url" in
  https://*) ;;
  *) exit 1 ;;
esac
authority="${url#https://}"
authority="${authority%%/*}"
authority="${authority##*@}"
prompt_host="${authority%%:*}"
[ "$prompt_host" = "$host" ] || exit 1

case "$prompt" in
  Username*)
    # GitLab accepts any non-empty user name with a project access token.
    printf '%s\n' "nexolab-gitlab-sync"
    ;;
  Password*)
    [ -n "${CREDENTIALS_DIRECTORY:-}" ] && [ -r "$token_file" ] || exit 1
    head -n 1 "$token_file"
    ;;
  *)
    exit 1
    ;;
esac
