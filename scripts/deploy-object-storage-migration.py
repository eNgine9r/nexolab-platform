#!/usr/bin/env python3
"""Copy current private, unversioned S3 objects and verify bytes before cutover.

Credentials are read only from environment. This helper never deletes source or
destination objects. The caller must freeze every source writer for final copy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

class MigrationError(ValueError):
    """A bounded, operator-safe migration failure reason."""


FIELDS = ("ContentType", "CacheControl", "ContentDisposition", "ContentEncoding", "ContentLanguage", "Expires", "Metadata")


def private_object(endpoint, bucket, key):
    url = f"{endpoint.rstrip('/')}/{urllib.parse.quote(bucket, safe='')}/{urllib.parse.quote(key, safe='/')}"
    try:
        with urllib.request.urlopen(url, timeout=5):
            raise MigrationError("object is anonymously readable")
    except urllib.error.HTTPError as error:
        if error.code not in {401, 403}:
            raise MigrationError("anonymous object check did not deny access") from error


def owner_only_acl(acl):
    owner = acl.get("Owner", {}).get("ID")
    if not owner or not acl.get("Grants"):
        raise MigrationError("cannot establish private owner-only ACL")
    for grant in acl["Grants"]:
        grantee = grant.get("Grantee", {})
        if grantee.get("Type") != "CanonicalUser" or grantee.get("ID") != owner or grant.get("Permission") != "FULL_CONTROL":
            raise MigrationError("custom or public ACL requires separately reviewed migration")


def metadata(head):
    return {key: (value.isoformat() if hasattr(value, "isoformat") else value)
            for key in FIELDS if (value := head.get(key)) is not None}


def inventory(s3, *, source_rules=True):
    result = {}
    for item in s3.list_buckets().get("Buckets", []):
        bucket = item["Name"]
        if source_rules:
            owner_only_acl(s3.get_bucket_acl(Bucket=bucket))
        if source_rules and s3.get_bucket_versioning(Bucket=bucket).get("Status"):
            raise MigrationError("versioned buckets require a separate history-preserving migration")
        # Policies and tags require separate semantics; never silently drop them.
        if source_rules:
            for method, missing in (("get_bucket_policy", "NoSuchBucketPolicy"),
                                    ("get_bucket_lifecycle_configuration", "NoSuchLifecycleConfiguration"),
                                    ("get_bucket_replication", "ReplicationConfigurationNotFoundError"),
                                    ("get_bucket_tagging", "NoSuchTagSet"),
                                    ("get_bucket_encryption", "ServerSideEncryptionConfigurationNotFoundError")):
                try:
                    getattr(s3, method)(Bucket=bucket)
                except Exception as error:
                    code = getattr(error, "response", {}).get("Error", {}).get("Code")
                    if code != missing:
                        raise MigrationError(f"cannot establish absence of source {method}") from error
                else:
                    raise MigrationError(f"source {method} configuration requires separately reviewed migration")
        objects = {}
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            for entry in page.get("Contents", []):
                key = entry["Key"]
                head = s3.head_object(Bucket=bucket, Key=key)
                if source_rules:
                    owner_only_acl(s3.get_object_acl(Bucket=bucket, Key=key))
                if source_rules and (any(head.get(field) for field in ("ServerSideEncryption", "SSECustomerAlgorithm", "ObjectLockMode", "ObjectLockRetainUntilDate", "ObjectLockLegalHoldStatus", "WebsiteRedirectLocation")) or head.get("StorageClass", "STANDARD") != "STANDARD"):
                    raise MigrationError("encryption, object lock, redirect or nonstandard storage class requires separate migration")
                if source_rules and s3.get_object_tagging(Bucket=bucket, Key=key).get("TagSet"):
                    raise MigrationError("tagged objects require a separately reviewed migration")
                objects[key] = {"size": head["ContentLength"], "etag": head["ETag"],
                                "last_modified": str(head.get("LastModified")), "metadata": metadata(head)}
        result[bucket] = objects
    return result


def digest(s3, bucket, key, expected=None):
    args = {"Bucket": bucket, "Key": key}
    if expected:
        args["IfMatch"] = expected["etag"]
    response = s3.get_object(**args)
    body = response["Body"]
    sha = hashlib.sha256()
    size = 0
    try:
        while chunk := body.read(1024 * 1024):
            sha.update(chunk)
            size += len(chunk)
    finally:
        body.close()
    if expected and (size != expected["size"] or metadata(response) != expected["metadata"]):
        raise MigrationError("source object changed while reading")
    return sha.hexdigest(), size


def copy_and_verify(source, target, *, private_check, checkpoint, dry_run=False):
    before = inventory(source)
    for bucket in before:
        private_check("source", bucket)
    if dry_run:
        return {"status": "inventory", "buckets": len(before),
                "objects": sum(len(items) for items in before.values()),
                "bytes": sum(item["size"] for items in before.values() for item in items.values())}
    target_buckets = {item["Name"] for item in target.list_buckets().get("Buckets", [])}
    if target_buckets - before.keys():
        raise MigrationError("unexpected target bucket; destination is not isolated")
    verified = []
    for bucket, objects in before.items():
        if bucket not in target_buckets:
            target.create_bucket(Bucket=bucket)
        private_check("target", bucket)
        for key, expected in objects.items():
            response = source.get_object(Bucket=bucket, Key=key, IfMatch=expected["etag"])
            body = response["Body"]
            sha = hashlib.sha256()
            size = 0
            with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as spool:
                try:
                    while chunk := body.read(1024 * 1024):
                        spool.write(chunk)
                        sha.update(chunk)
                        size += len(chunk)
                finally:
                    body.close()
                if size != expected["size"] or metadata(response) != expected["metadata"]:
                    raise MigrationError("source object changed during copy")
                source_sha = sha.hexdigest()
                # Resume by accepting only an independently byte-verified target.
                same = False
                try:
                    head = target.head_object(Bucket=bucket, Key=key)
                except Exception as error:
                    code = getattr(error, "response", {}).get("Error", {}).get("Code")
                    if code not in {"404", "NoSuchKey", "NotFound"}:
                        raise
                else:
                    same = (metadata(head) == expected["metadata"] and
                            digest(target, bucket, key) == (source_sha, size))
                if not same:
                    spool.seek(0)
                    extra = {field: response[field] for field in FIELDS if response.get(field) is not None}
                    target.upload_fileobj(spool, bucket, key, ExtraArgs=extra)
                head = target.head_object(Bucket=bucket, Key=key)
                if metadata(head) != expected["metadata"] or digest(target, bucket, key) != (source_sha, size):
                    raise MigrationError("target content or metadata verification failed")
            verified.append({"bucket": bucket, "key": key, "bytes": size,
                             "sha256": source_sha, "metadata": expected["metadata"]})
            checkpoint({"status": "copying", "objects": verified})
        actual = set()
        for page in target.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            actual.update(item["Key"] for item in page.get("Contents", []))
        if actual != objects.keys():
            raise MigrationError("target key set differs; no objects were deleted")
    if inventory(source) != before:
        raise MigrationError("source changed; keep legacy storage active and repeat under write freeze")
    # Re-read source bytes after copying to detect changes hidden by metadata.
    for item in verified:
        if digest(source, item["bucket"], item["key"], before[item["bucket"]][item["key"]]) != (item["sha256"], item["bytes"]):
            raise MigrationError("source bytes changed before final acceptance")
    for bucket in before:
        private_check("source", bucket)
        private_check("target", bucket)
    return {"schema_version": 1, "kind": "nexolab-object-storage-migration",
            "status": "verified", "verified_at": datetime.now(timezone.utc).isoformat(),
            "buckets": sorted(before), "objects": verified,
            "total_bytes": sum(item["bytes"] for item in verified)}


def atomic_json(path, document):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".partial")
    with temporary.open("w", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(document, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def validate_proof(proof, target_source, inspect, is_ancestor=lambda _old, _new: False, require_cutover=False):
    """Check the exact frozen source and candidate identities before deployment."""
    if proof.get("schema_version") != 1 or proof.get("kind") != "nexolab-object-storage-migration" or proof.get("status") != "verified":
        raise MigrationError("verified migration authority is required")
    if require_cutover and proof.get("cutover_verified") is not True:
        raise MigrationError("completed cutover authority is required for deployment")
    approved_source = proof.get("target_source", "")
    if not re.fullmatch(r"[0-9a-f]{40}", target_source) or not re.fullmatch(r"[0-9a-f]{40}", approved_source):
        raise MigrationError("migration source revision differs from deployment target")
    if approved_source != target_source and (proof.get("cutover_verified") is not True or not is_ancestor(approved_source, target_source)):
        raise MigrationError("migration authority is not in the approved target lineage")
    objects = proof.get("objects")
    buckets = proof.get("buckets")
    if not isinstance(objects, list) or not isinstance(buckets, list):
        raise MigrationError("complete migration manifest is required")
    identities = set()
    total = 0
    for item in objects:
        pair = (item.get("bucket"), item.get("key"))
        if pair in identities or pair[0] not in buckets or not isinstance(pair[1], str):
            raise MigrationError("invalid or repeated object identity")
        identities.add(pair)
        if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))) or type(item.get("bytes")) is not int or item["bytes"] < 0:
            raise MigrationError("object integrity evidence is invalid")
        total += item["bytes"]
    if proof.get("total_bytes") != total:
        raise MigrationError("migration byte total is inconsistent")
    volume = inspect("volume", "nexolab-central-object-storage-versitygw-data")
    if volume.get("CreatedAt") != proof.get("target_volume_created_at") or volume.get("Name") != "nexolab-central-object-storage-versitygw-data":
        raise MigrationError("candidate volume identity changed")
    image = inspect("image", "nexolab/object-storage:versitygw-v1.8.0")
    if image.get("Id") != proof.get("target_image_id"):
        raise MigrationError("candidate image identity changed")
    if proof.get("cutover_verified") is True:
        inspect("image", proof["source_image_id"])
        legacy = inspect("volume", "nexolab-central-object-storage-data")
        if legacy.get("Name") != "nexolab-central-object-storage-data":
            raise MigrationError("retained legacy rollback volume is missing")
        # Compose may legitimately recreate a container around the same accepted
        # immutable image and persistent volume. Resolve exactly one live service;
        # retain the original cutover container ID in the manifest for audit.
        target = inspect("active_storage", "nexolab-central")
        if target.get("Image") != proof["target_image_id"] or target.get("State", {}).get("Running") is not True:
            raise MigrationError("accepted target storage identity or state changed")
        if not any(m.get("Name") == volume["Name"] and m.get("Destination") == "/data" for m in target.get("Mounts", [])):
            raise MigrationError("accepted target storage volume changed")
        return
    writer = inspect("container", proof["frozen_writer_id"])
    if writer.get("State", {}).get("Running") is not False or writer.get("Image") != proof.get("source_writer_image_id"):
        raise MigrationError("source writer must remain frozen until activation")
    source = inspect("container", proof["source_container_id"])
    if source.get("Image") != proof.get("source_image_id") or source.get("State", {}).get("Running") is not True:
        raise MigrationError("legacy source identity or state changed")
    if not any(m.get("Name") == "nexolab-central-object-storage-data" and m.get("Destination") == "/data" for m in source.get("Mounts", [])):
        raise MigrationError("legacy source volume identity changed")


def docker_inspect(kind, identity):
    if kind == "active_storage":
        ids = subprocess.check_output(["docker", "ps", "-q", "--filter", "label=com.docker.compose.project=nexolab-central",
            "--filter", "label=com.docker.compose.service=minio"], text=True).splitlines()
        if len(ids) != 1:
            raise MigrationError("exactly one active accepted storage service is required")
        kind, identity = "container", ids[0]
    return json.loads(subprocess.check_output(["docker", kind, "inspect", identity], text=True))[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write-freeze-confirmed", action="store_true")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--validate-proof", action="store_true")
    parser.add_argument("--verify-target", action="store_true")
    parser.add_argument("--require-cutover", action="store_true")
    parser.add_argument("--expected-target-source")
    args = parser.parse_args()
    if args.validate_proof:
        if args.manifest.is_symlink() or not args.manifest.is_file():
            raise MigrationError("regular migration authority file is required")
        validate_proof(json.loads(args.manifest.read_text()), args.expected_target_source or "", docker_inspect,
            is_ancestor=lambda old, new: subprocess.run(["git", "merge-base", "--is-ancestor", old, new], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0,
            require_cutover=args.require_cutover)
        print("OBJECT_STORAGE_MIGRATION_AUTHORITY_VALIDATED")
        return
    if args.verify_target:
        import importlib.util
        spec = importlib.util.spec_from_file_location("s3_helper", Path(__file__).with_name("object-storage-s3.py"))
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        endpoint = os.environ["TARGET_ENDPOINT"]
        target = helper.client(argparse.Namespace(endpoint=endpoint, access_key=os.environ["MINIO_ROOT_USER"],
            secret_key=os.environ["MINIO_ROOT_PASSWORD"], region=os.environ.get("OBJECT_STORAGE_REGION", "us-east-1")))
        helper.wait_ready(target, 60)
        manifest = json.loads(args.manifest.read_text())
        if manifest.get("status") != "verified":
            raise MigrationError("verified manifest required")
        actual = inventory(target, source_rules=False)
        expected = {(item["bucket"], item["key"]): item for item in manifest["objects"]}
        if sorted(actual) != manifest["buckets"] or {(b, k) for b, items in actual.items() for k in items} != expected.keys():
            raise MigrationError("active target bucket/key set changed")
        for (bucket, key), item in expected.items():
            if actual[bucket][key]["metadata"] != item["metadata"] or digest(target, bucket, key) != (item["sha256"], item["bytes"]):
                raise MigrationError("active target integrity changed")
            private_object(endpoint, bucket, key)
            signed = target.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=60)
            sha = hashlib.sha256()
            size = 0
            with urllib.request.urlopen(signed, timeout=10) as response:
                while chunk := response.read(1024 * 1024):
                    sha.update(chunk)
                    size += len(chunk)
            if (sha.hexdigest(), size) != (item["sha256"], item["bytes"]):
                raise MigrationError("signed object GET verification failed")
        for bucket in manifest["buckets"]:
            helper.assert_private(endpoint, bucket)
        print("ACTIVE_TARGET_STORAGE_VERIFIED")
        return
    if not args.dry_run and not args.write_freeze_confirmed:
        parser.error("final copy requires every source writer to be frozen")
    import importlib.util
    spec = importlib.util.spec_from_file_location("s3_helper", Path(__file__).with_name("object-storage-s3.py"))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    endpoints = {}
    clients = {}
    for side in ("source", "target"):
        prefix = side.upper()
        endpoint = os.environ.get(f"{prefix}_ENDPOINT")
        access = os.environ.get("MINIO_ROOT_USER")
        secret = os.environ.get("MINIO_ROOT_PASSWORD")
        if not endpoint or not access or not secret:
            parser.error("protected endpoint and credential environment is incomplete")
        endpoints[side] = endpoint
        clients[side] = helper.client(argparse.Namespace(endpoint=endpoint,
            access_key=access, secret_key=secret, region=os.environ.get("OBJECT_STORAGE_REGION", "us-east-1")))
        helper.wait_ready(clients[side], 60)
    if endpoints["source"].rstrip("/") == endpoints["target"].rstrip("/"):
        parser.error("source and target endpoints must differ")
    args.manifest.unlink(missing_ok=True)  # Invalidate prior acceptance before copying.
    result = copy_and_verify(clients["source"], clients["target"],
        private_check=lambda side, bucket: helper.assert_private(endpoints[side], bucket),
        checkpoint=lambda doc: atomic_json(args.manifest.with_suffix(".progress.json"), doc),
        dry_run=args.dry_run)
    atomic_json(args.manifest, result)
    print(json.dumps({"status": result["status"], "objects": len(result.get("objects", [])) if not args.dry_run else result["objects"],
                      "bytes": result.get("total_bytes", result.get("bytes"))}))


if __name__ == "__main__":
    try:
        main()
    except MigrationError as error:
        print(f"Migration failed closed: {error}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as error:
        # S3 errors can contain endpoints or credential material. Keep output bounded.
        print(f"Migration failed closed: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1)
