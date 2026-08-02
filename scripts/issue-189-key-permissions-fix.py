from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:90]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    script = "scripts/run-disaster-recovery-acceptance.sh"
    replace_once(
        script,
        'SECRETS_DIR="$PRIVATE_DIR/secrets"\nRESTORE_LOCAL_AUTH_DIR="$PRIVATE_DIR/restore-local-auth"',
        'SECRETS_DIR="$PRIVATE_DIR/secrets"\nSOURCE_LOCAL_AUTH_DIR="$PRIVATE_DIR/source-local-auth"\nRESTORE_LOCAL_AUTH_DIR="$PRIVATE_DIR/restore-local-auth"',
    )
    replace_once(
        script,
        'mkdir -p "$SECRETS_DIR" "$RESTORE_LOCAL_AUTH_DIR" "$WORK_DIR" "$PAYLOAD_DIR" "$EVIDENCE_DIR"',
        'mkdir -p "$SECRETS_DIR" "$SOURCE_LOCAL_AUTH_DIR" "$RESTORE_LOCAL_AUTH_DIR" "$WORK_DIR" "$PAYLOAD_DIR" "$EVIDENCE_DIR"',
    )
    replace_once(
        script,
        'chmod 0755 "$SECRETS_DIR" "$RESTORE_LOCAL_AUTH_DIR"',
        'chmod 0755 "$SECRETS_DIR" "$SOURCE_LOCAL_AUTH_DIR" "$RESTORE_LOCAL_AUTH_DIR"',
    )
    replace_once(
        script,
        'export DR_SECRETS_DIR="$SECRETS_DIR"\nexport DR_RESTORE_LOCAL_AUTH_DIR="$RESTORE_LOCAL_AUTH_DIR"',
        'export DR_SECRETS_DIR="$SECRETS_DIR"\nexport DR_SOURCE_LOCAL_AUTH_DIR="$SOURCE_LOCAL_AUTH_DIR"\nexport DR_RESTORE_LOCAL_AUTH_DIR="$RESTORE_LOCAL_AUTH_DIR"',
    )

    anchor = """write_raw_key() {
  local path=$1
  python3 - "$path" <<'PY'
from pathlib import Path
import secrets
import sys
path = Path(sys.argv[1])
path.write_bytes(secrets.token_bytes(32))
path.chmod(0o600)
PY
}

"""
    helper = """prepare_runtime_local_auth_dir() {
  local private_source=$1
  local public_source=$2
  local target_dir=$3
  install -m 0600 "$private_source" "$target_dir/private.pem"
  install -m 0644 "$public_source" "$target_dir/public.pem"
  docker run --rm \\
    --user 0:0 \\
    --volume "$target_dir:/run/local-auth" \\
    --entrypoint /bin/sh \\
    "$DR_TELEMETRY_IMAGE" \\
    -ec '
      chown 10001:10001 /run/local-auth/private.pem /run/local-auth/public.pem
      chmod 0400 /run/local-auth/private.pem
      chmod 0444 /run/local-auth/public.pem
    '
}

"""
    replace_once(script, anchor, anchor + helper)
    replace_once(
        script,
        "compose build source-migrate source-mqtt\ncompose up -d --wait source-postgres source-minio source-mqtt",
        "compose build source-migrate source-mqtt\nprepare_runtime_local_auth_dir \\\n  \"$SECRETS_DIR/local-auth-private.pem\" \\\n  \"$SECRETS_DIR/local-auth-public.pem\" \\\n  \"$SOURCE_LOCAL_AUTH_DIR\"\ncompose up -d --wait source-postgres source-minio source-mqtt",
    )

    replace_once(
        script,
        'install -m 0600 "$RESTORED_DIR/local-auth/private.pem" "$RESTORE_LOCAL_AUTH_DIR/private.pem"\n',
        "",
    )
    replace_once(
        script,
        'install -m 0644 "$RESTORED_DIR/local-auth/public.pem" "$RESTORE_LOCAL_AUTH_DIR/public.pem"\n',
        "",
    )
    replace_once(
        script,
        'openssl pkey -in "$RESTORE_LOCAL_AUTH_DIR/private.pem" -pubout -outform DER',
        'openssl pkey -in "$RESTORED_DIR/local-auth/private.pem" -pubout -outform DER',
    )
    replace_once(
        script,
        'openssl pkey -pubin -in "$RESTORE_LOCAL_AUTH_DIR/public.pem" -outform DER',
        'openssl pkey -pubin -in "$RESTORED_DIR/local-auth/public.pem" -outform DER',
    )
    replace_once(
        script,
        'cmp "$WORK_DIR/restored-private-public.sha256" "$WORK_DIR/restored-public.sha256"\n',
        'cmp "$WORK_DIR/restored-private-public.sha256" "$WORK_DIR/restored-public.sha256"\nprepare_runtime_local_auth_dir \\\n  "$RESTORED_DIR/local-auth/private.pem" \\\n  "$RESTORED_DIR/local-auth/public.pem" \\\n  "$RESTORE_LOCAL_AUTH_DIR"\n',
    )

    overlay = "infrastructure/compose/compose.disaster-recovery-local-auth.yaml"
    replace_once(
        overlay,
        "AUTH_LOCAL_PRIVATE_KEY_FILE: /run/secrets/nexolab/local-auth-private.pem",
        "AUTH_LOCAL_PRIVATE_KEY_FILE: /run/secrets/local-auth/private.pem",
    )
    replace_once(
        overlay,
        "AUTH_LOCAL_PUBLIC_KEY_FILE: /run/secrets/nexolab/local-auth-public.pem",
        "AUTH_LOCAL_PUBLIC_KEY_FILE: /run/secrets/local-auth/public.pem",
    )
    replace_once(
        overlay,
        "      - ${DR_SECRETS_DIR:?DR_SECRETS_DIR is required}:/run/secrets/nexolab:ro\n    depends_on:",
        "      - ${DR_SECRETS_DIR:?DR_SECRETS_DIR is required}:/run/secrets/nexolab:ro\n      - ${DR_SOURCE_LOCAL_AUTH_DIR:?DR_SOURCE_LOCAL_AUTH_DIR is required}:/run/secrets/local-auth:ro\n    depends_on:",
    )


if __name__ == "__main__":
    main()
