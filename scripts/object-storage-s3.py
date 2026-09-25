#!/usr/bin/env python3
"""Small repository-owned S3 administration/backup helper for local object storage."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Iterable

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in {None, ""} else default


def client(args: argparse.Namespace):
    return boto3.client(
        "s3",
        endpoint_url=args.endpoint,
        region_name=args.region,
        aws_access_key_id=args.access_key,
        aws_secret_access_key=args.secret_key,
        config=Config(
            signature_version="s3v4",
            connect_timeout=2,
            read_timeout=5,
            retries={"max_attempts": 2, "mode": "standard"},
            s3={"addressing_style": "path"},
        ),
    )


def wait_ready(s3, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            s3.list_buckets()
            return
        except (BotoCoreError, ClientError) as exc:
            last_error = exc
            time.sleep(0.25)
    raise SystemExit(f"object storage did not become ready within {timeout:g}s: {type(last_error).__name__}")


def ensure_bucket(s3, bucket: str, timeout: float) -> None:
    wait_ready(s3, timeout)
    try:
        s3.head_bucket(Bucket=bucket)
        return
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0) or 0)
        if code not in {"404", "NoSuchBucket", "NotFound"} and status != 404:
            raise
    s3.create_bucket(Bucket=bucket)
    s3.head_bucket(Bucket=bucket)


def object_keys(s3, bucket: str) -> Iterable[str]:
    token: str | None = None
    while True:
        kwargs = {"Bucket": bucket}
        if token:
            kwargs["ContinuationToken"] = token
        response = s3.list_objects_v2(**kwargs)
        for item in response.get("Contents", []):
            key = item.get("Key")
            if isinstance(key, str):
                yield key
        if not response.get("IsTruncated"):
            return
        token = response.get("NextContinuationToken")
        if not isinstance(token, str) or not token:
            raise RuntimeError("truncated S3 listing omitted continuation token")


def safe_target(root: Path, key: str) -> Path:
    pure = PurePosixPath(key)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise SystemExit(f"unsafe object key for filesystem restore: {key!r}")
    target = root.joinpath(*pure.parts)
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    if resolved_target != resolved_root and resolved_root not in resolved_target.parents:
        raise SystemExit(f"object key escapes restore root: {key!r}")
    return target


def unsigned_bucket_url(endpoint: str, bucket: str) -> str:
    return f"{endpoint.rstrip('/')}/{urllib.parse.quote(bucket, safe='')}?list-type=2"


def assert_private(endpoint: str, bucket: str) -> None:
    request = urllib.request.Request(unsigned_bucket_url(endpoint, bucket), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            print("private")
            return
        raise SystemExit(f"unexpected anonymous bucket status: {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"anonymous bucket check failed: {exc.reason}") from exc
    raise SystemExit(f"bucket is anonymously readable (HTTP {status})")


def load_metadata(path: Path | None) -> dict[str, dict[str, object]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    objects = payload.get("objects") if isinstance(payload, dict) else None
    if not isinstance(objects, list):
        raise SystemExit("object metadata file must contain an objects list")
    result: dict[str, dict[str, object]] = {}
    for item in objects:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise SystemExit("object metadata entry is invalid")
        result[item["key"]] = item
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default=env("OBJECT_STORAGE_ENDPOINT_URL", "http://minio:9000"))
    parser.add_argument("--region", default=env("OBJECT_STORAGE_REGION", "us-east-1"))
    parser.add_argument("--access-key", default=env("OBJECT_STORAGE_ACCESS_KEY_ID", env("MINIO_ROOT_USER")))
    parser.add_argument("--secret-key", default=env("OBJECT_STORAGE_SECRET_ACCESS_KEY", env("MINIO_ROOT_PASSWORD")))
    parser.add_argument("--timeout", type=float, default=60.0)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("wait")
    for name in ("ensure-bucket", "assert-private", "list"):
        command = sub.add_parser(name)
        command.add_argument("--bucket", required=True)

    put = sub.add_parser("put-file")
    put.add_argument("--bucket", required=True)
    put.add_argument("--key", required=True)
    put.add_argument("--path", required=True, type=Path)
    put.add_argument("--content-type")

    get = sub.add_parser("get-file")
    get.add_argument("--bucket", required=True)
    get.add_argument("--key", required=True)
    get.add_argument("--path", required=True, type=Path)

    cat = sub.add_parser("cat")
    cat.add_argument("--bucket", required=True)
    cat.add_argument("--key", required=True)

    upload = sub.add_parser("mirror-upload")
    upload.add_argument("--bucket", required=True)
    upload.add_argument("--source-dir", required=True, type=Path)
    upload.add_argument("--metadata-file", type=Path)

    download = sub.add_parser("mirror-download")
    download.add_argument("--bucket", required=True)
    download.add_argument("--destination", required=True, type=Path)

    stat = sub.add_parser("stat-keys")
    stat.add_argument("--bucket", required=True)
    stat.add_argument("--keys-file", required=True, type=Path)

    args = parser.parse_args()
    if not args.access_key or not args.secret_key:
        parser.error("object-storage access key and secret key are required")
    s3 = client(args)

    if args.command == "wait":
        wait_ready(s3, args.timeout)
    elif args.command == "ensure-bucket":
        ensure_bucket(s3, args.bucket, args.timeout)
    elif args.command == "assert-private":
        wait_ready(s3, args.timeout)
        assert_private(args.endpoint, args.bucket)
    elif args.command == "list":
        wait_ready(s3, args.timeout)
        for key in object_keys(s3, args.bucket):
            print(key)
    elif args.command == "put-file":
        wait_ready(s3, args.timeout)
        extra: dict[str, str] = {}
        content_type = args.content_type or mimetypes.guess_type(args.path.name)[0]
        if content_type:
            extra["ContentType"] = content_type
        s3.upload_file(str(args.path), args.bucket, args.key, ExtraArgs=extra or None)
    elif args.command == "get-file":
        wait_ready(s3, args.timeout)
        args.path.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(args.bucket, args.key, str(args.path))
    elif args.command == "cat":
        wait_ready(s3, args.timeout)
        body = s3.get_object(Bucket=args.bucket, Key=args.key)["Body"].read()
        sys.stdout.buffer.write(body)
    elif args.command == "mirror-upload":
        wait_ready(s3, args.timeout)
        root = args.source_dir.resolve()
        metadata = load_metadata(args.metadata_file)
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            key = path.relative_to(root).as_posix()
            recorded = metadata.get(key, {})
            content_type = recorded.get("content_type") or mimetypes.guess_type(path.name)[0]
            user_metadata = recorded.get("metadata")
            kwargs: dict[str, object] = {}
            if isinstance(content_type, str) and content_type:
                kwargs["ContentType"] = content_type
            if isinstance(user_metadata, dict) and all(
                isinstance(k, str) and isinstance(v, str) for k, v in user_metadata.items()
            ):
                kwargs["Metadata"] = user_metadata
            s3.upload_file(str(path), args.bucket, key, ExtraArgs=kwargs or None)
    elif args.command == "mirror-download":
        wait_ready(s3, args.timeout)
        args.destination.mkdir(parents=True, exist_ok=True)
        for key in object_keys(s3, args.bucket):
            target = safe_target(args.destination, key)
            target.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(args.bucket, key, str(target))
    elif args.command == "stat-keys":
        wait_ready(s3, args.timeout)
        for key in args.keys_file.read_text(encoding="utf-8").splitlines():
            if not key:
                continue
            response = s3.head_object(Bucket=args.bucket, Key=key)
            print(json.dumps({
                "key": key,
                "size": response["ContentLength"],
                "etag": response["ETag"],
                "content_type": response.get("ContentType"),
                "metadata": response.get("Metadata") or {},
            }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
