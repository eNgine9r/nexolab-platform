#!/usr/bin/env bash
# Development CI only. Same scanner version as the pinned trivy-action;
# bypass the upstream get.trivy.dev download gateway, never the scans.
set -euo pipefail

if [[ $# != 1 || $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
  echo 'Usage: install-ci-trivy.sh DESTINATION (Linux x86_64 only)' >&2
  exit 64
fi

destination=$1
version=0.70.0
asset="trivy_${version}_Linux-64bit.tar.gz"
# Official v0.70.0 release checksums, retrieved 2026-11-04:
# https://github.com/aquasecurity/trivy/releases/download/v0.70.0/trivy_0.70.0_checksums.txt
expected_sha256=8b4376d5d6befe5c24d503f10ff136d9e0c49f9127a4279fd110b727929a5aa9
temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT

curl --fail --location --silent --show-error \
  --proto '=https' --proto-redir '=https' \
  --connect-timeout 15 --max-time 120 --retry 2 \
  "https://github.com/aquasecurity/trivy/releases/download/v${version}/${asset}" \
  --output "$temporary/$asset"
printf '%s  %s\n' "$expected_sha256" "$temporary/$asset" | sha256sum --check --status
# Extract only the verified executable; do not run an upstream install script.
tar --extract --gzip --file "$temporary/$asset" --directory "$temporary" -- trivy
if [[ ! -f "$temporary/trivy" || -L "$temporary/trivy" ]]; then
  echo 'Verified archive did not contain a regular Trivy executable' >&2
  exit 65
fi
"$temporary/trivy" --version | head -1 | grep -Fx "Version: $version"
install -d -- "$destination"
install -m 0755 -- "$temporary/trivy" "$destination/trivy"
