#!/usr/bin/env bash
# Approved #1249 migration prerequisite; old storage is retained for rollback.
set -Eeuo pipefail
umask 077
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# == 2 && "$1" == --expected-deployed-source && "$2" =~ ^[0-9a-f]{40}$ ]] || {
  echo 'Usage: migrate-object-storage-raspberry-pi.sh --expected-deployed-source SHA' >&2
  exit 64
}
EXPECTED="$2"
cd "$REPO"
[[ "$(git branch --show-current)" == main ]] || { echo 'Run only from accepted main' >&2; exit 1; }
git diff --quiet && git diff --cached --quiet
TARGET="$(git rev-parse HEAD)"
sudo -n true
exec 8>"${XDG_RUNTIME_DIR:-/tmp}/nexolab-object-storage-migration.lock"
flock -n 8 || { echo 'Another migration is running' >&2; exit 75; }
bash scripts/deploy-current-head-raspberry-pi.sh --runtime-mode lan \
  --source-ref "$TARGET" --expected-deployed-source "$EXPECTED" --source-selection-check-only
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE="$REPO/runtime/object-storage-migration/$STAMP"
mkdir -p "$EVIDENCE"
SOURCE="$(docker ps -q --filter label=com.docker.compose.project=nexolab-central --filter label=com.docker.compose.service=minio)"
WRITER="$(docker ps -q --filter label=com.docker.compose.project=nexolab-central --filter label=com.docker.compose.service=telemetry-service)"
[[ "$SOURCE" =~ ^[0-9a-f]+$ && "$WRITER" =~ ^[0-9a-f]+$ ]] || { echo 'Exactly one live source and writer required' >&2; exit 1; }
SOURCE="$(docker inspect --format '{{.Id}}' "$SOURCE")"
WRITER="$(docker inspect --format '{{.Id}}' "$WRITER")"
SOURCE_IMAGE="$(docker inspect --format '{{.Image}}' "$SOURCE")"
WRITER_IMAGE="$(docker inspect --format '{{.Image}}' "$WRITER")"
docker image tag "$SOURCE_IMAGE" "nexolab/minio-rollback:1249-$STAMP"
[[ "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}' "$SOURCE")" == nexolab-central-object-storage-data ]] || {
  echo 'Legacy storage identity differs; no migration performed' >&2; exit 1;
}
docker run --rm --network none --entrypoint python "$WRITER_IMAGE" -c 'import boto3'
docker build --tag nexolab/object-storage:versitygw-v1.8.0 infrastructure/object-storage
TARGET_IMAGE="$(docker image inspect --format '{{.Id}}' nexolab/object-storage:versitygw-v1.8.0)"
VOLUME=nexolab-central-object-storage-versitygw-data
if docker volume inspect "$VOLUME" >/dev/null 2>&1; then
  [[ "$(docker volume inspect --format '{{index .Labels "nexolab.migration"}}' "$VOLUME")" == pending-1249 ]] || {
    echo 'Existing target has no migration ownership; refusing to overwrite' >&2; exit 1;
  }
else
  docker volume create --label nexolab.migration=pending-1249 "$VOLUME" >/dev/null
fi
CREATED="$(docker volume inspect --format '{{.CreatedAt}}' "$VOLUME")"
NAME="nexolab-storage-migration-1249"
if docker container inspect "$NAME" >/dev/null 2>&1; then
  echo 'Prior candidate exists: inspect its evidence before retrying; no container removed' >&2
  exit 1
fi
# Extract only required credentials into private temporary env files; never log them.
python3 - "$SOURCE" "$WRITER" "$EVIDENCE" <<'PY'
import json, os, pathlib, subprocess, sys
data = json.loads(subprocess.check_output(['docker', 'inspect', sys.argv[1]], text=True))[0]
writer = json.loads(subprocess.check_output(['docker', 'inspect', sys.argv[2]], text=True))[0]
env = dict(item.split('=', 1) for item in data['Config']['Env'] if '=' in item)
writer_env = dict(item.split('=', 1) for item in writer['Config']['Env'] if '=' in item)
access, secret = env.get('MINIO_ROOT_USER'), env.get('MINIO_ROOT_PASSWORD')
region = writer_env.get('OBJECT_STORAGE_REGION', 'us-east-1')
if not access or not secret or any(c in access + secret + region for c in '\r\n'):
    raise SystemExit('Protected legacy credential environment is incomplete')
root = pathlib.Path(sys.argv[3])
(root / 'candidate.env').write_text(f'ROOT_ACCESS_KEY_ID={access}\nROOT_SECRET_ACCESS_KEY={secret}\nVGW_PORT=:9000\nVGW_REGION={region}\nVGW_HEALTH=/health\nVGW_QUIET=true\n')
(root / 'helper.env').write_text(f'MINIO_ROOT_USER={access}\nMINIO_ROOT_PASSWORD={secret}\nSOURCE_ENDPOINT=http://minio:9000\nTARGET_ENDPOINT=http://nexolab-storage-migration-1249:9000\nOBJECT_STORAGE_REGION={region}\n')
# Keep exact legacy config privately for rollback before any target writes.
rollback = {'services': {'minio': {'image': data['Image'],
    'entrypoint': data['Config'].get('Entrypoint'), 'command': data['Config'].get('Cmd'),
    'environment': env, 'read_only': data['HostConfig'].get('ReadonlyRootfs', False),
    'volumes': ['migration-legacy-storage:/data']}},
    'volumes': {'migration-legacy-storage': {'external': True, 'name': 'nexolab-central-object-storage-data'}}}
(root / 'rollback-storage.json').write_text(json.dumps(rollback))
config = json.loads(subprocess.check_output(['docker', 'compose', '--env-file', 'infrastructure/compose/.env.central', '-f', 'infrastructure/compose/compose.central.yaml', 'config', '--format', 'json'], text=True))
candidate_env = config['services']['minio']['environment']
if candidate_env.get('ROOT_ACCESS_KEY_ID') != access or candidate_env.get('ROOT_SECRET_ACCESS_KEY') != secret or candidate_env.get('VGW_REGION') != region:
    raise SystemExit('Compose storage credentials/region differ from live source; no activation')
for path in (root / 'candidate.env', root / 'helper.env'):
    os.chmod(path, 0o600)
os.chmod(root / 'rollback-storage.json', 0o600)
PY
FROZEN=0
DEPLOY_STARTED=0
STORAGE_SWITCH_STARTED=0
cleanup() {
  local result=$?
  trap - EXIT
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -f -- "$EVIDENCE/candidate.env" "$EVIDENCE/helper.env"
  if [[ "$FROZEN" == 1 && "$DEPLOY_STARTED" == 0 ]]; then
    if [[ "$STORAGE_SWITCH_STARTED" == 1 ]]; then
      if ! docker compose --env-file infrastructure/compose/.env.central \
        -f infrastructure/compose/compose.central.yaml -f "$EVIDENCE/rollback-storage.json" \
        up -d --no-deps --no-build minio; then
        echo 'Legacy storage rollback failed; Telemetry remains frozen. Inspect protected migration evidence.' >&2
        exit 1
      fi
    fi
    # Before deployment, only restart the unchanged exact writer, never an old schema image after activation.
    docker start "$WRITER" >/dev/null || result=1
  fi
  if [[ "$result" != 0 && "$DEPLOY_STARTED" == 1 ]]; then
    echo "Deployment was attempted; use its canonical recovery evidence. Migration: $EVIDENCE" >&2
  fi
  exit "$result"
}
trap cleanup EXIT
docker run -d --name "$NAME" --network nexolab-central --read-only \
  --security-opt no-new-privileges:true --env-file "$EVIDENCE/candidate.env" \
  --mount "type=volume,src=$VOLUME,dst=/data" "$TARGET_IMAGE" posix /data >/dev/null
run_helper() {
  docker run --rm --network nexolab-central --user "$(id -u):$(id -g)" \
    --security-opt no-new-privileges:true --read-only --tmpfs /tmp:rw,size=256m \
    --env-file "$EVIDENCE/helper.env" \
    --mount "type=bind,src=$REPO/scripts,dst=/scripts,readonly" \
    --mount "type=bind,src=$EVIDENCE,dst=/evidence" \
    --entrypoint python "$WRITER_IMAGE" /scripts/deploy-object-storage-migration.py "$@"
}
run_helper --dry-run --manifest /evidence/inventory.json
python3 - "$EVIDENCE/inventory.json" "$REPO" <<'PY'
import json, shutil, sys
inventory = json.load(open(sys.argv[1]))
if shutil.disk_usage(sys.argv[2]).free < inventory['bytes'] * 2 + 2 * 1024**3:
    raise SystemExit('Insufficient capacity for object migration plus reserve')
PY
echo 'Freezing Telemetry API writes; edge acquisition continues buffering. Keep this terminal open.'
FROZEN=1
docker stop --time 30 "$WRITER" >/dev/null
[[ "$(docker inspect --format '{{.State.Running}}' "$WRITER")" == false ]]
run_helper --write-freeze-confirmed --manifest /evidence/manifest.json
python3 - "$EVIDENCE/manifest.json" "$TARGET" "$SOURCE" "$SOURCE_IMAGE" "$WRITER" "$WRITER_IMAGE" "$TARGET_IMAGE" "$CREATED" <<'PY'
import json, os, pathlib, sys
path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text())
data.update(dict(zip(('target_source', 'source_container_id', 'source_image_id', 'frozen_writer_id', 'source_writer_image_id', 'target_image_id', 'target_volume_created_at'), sys.argv[2:])))
authority = path.parents[1] / 'authority.json'
temporary = authority.with_suffix('.partial')
with temporary.open('w') as stream:
    os.chmod(temporary, 0o600)
    json.dump(data, stream, indent=2)
    stream.flush()
    os.fsync(stream.fileno())
os.replace(temporary, authority)
PY
python3 scripts/deploy-object-storage-migration.py --validate-proof \
  --manifest runtime/object-storage-migration/authority.json --expected-target-source "$TARGET"
docker rm -f "$NAME" >/dev/null
# This is the separately authorized storage cutover. No application writes have
# occurred on the target, so failure here can restore legacy storage safely.
STORAGE_SWITCH_STARTED=1
docker compose --env-file infrastructure/compose/.env.central \
  -f infrastructure/compose/compose.central.yaml up -d --no-deps --no-build minio
ACTIVE_STORAGE="$(docker ps -q --filter label=com.docker.compose.project=nexolab-central --filter label=com.docker.compose.service=minio)"
[[ "$(docker inspect --format '{{.Image}}' "$ACTIVE_STORAGE")" == "$TARGET_IMAGE" ]]
[[ "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}' "$ACTIVE_STORAGE")" == "$VOLUME" ]]
python3 - "$EVIDENCE/helper.env" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
path.write_text(path.read_text().replace('TARGET_ENDPOINT=http://nexolab-storage-migration-1249:9000', 'TARGET_ENDPOINT=http://minio:9000'))
PY
run_helper --verify-target --manifest /evidence/manifest.json
python3 - runtime/object-storage-migration/authority.json "$ACTIVE_STORAGE" <<'PY'
import json, os, pathlib, sys
path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text())
data.update(cutover_verified=True, target_container_id=sys.argv[2])
temporary = path.with_suffix('.partial')
with temporary.open('w') as stream:
    os.chmod(temporary, 0o600)
    json.dump(data, stream, indent=2)
    stream.flush()
    os.fsync(stream.fileno())
os.replace(temporary, path)
PY
docker start "$WRITER" >/dev/null
FROZEN=0
echo 'Storage cutover verified; Telemetry writes resumed. Starting canonical project update.'
DEPLOY_STARTED=1
bash scripts/deploy-current-head-raspberry-pi.sh --runtime-mode lan \
  --source-ref "$TARGET" --expected-deployed-source "$EXPECTED"
echo "Storage migration and controlled deployment passed. Legacy volume/image retained. Evidence: $EVIDENCE"
