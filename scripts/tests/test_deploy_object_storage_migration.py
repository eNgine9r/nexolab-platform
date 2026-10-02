from __future__ import annotations

import copy
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("migration", ROOT / "scripts/deploy-object-storage-migration.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class Missing(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}


class S3:
    def __init__(self, buckets=None):
        self.buckets = copy.deepcopy(buckets or {})
        self.uploads = 0
        self.versioning = None
        self.policy = False
        self.tags = []
        self.acl = {"Owner": {"ID": "owner"}, "Grants": [{"Grantee": {"Type": "CanonicalUser", "ID": "owner"}, "Permission": "FULL_CONTROL"}]}
        self.lifecycle = False
        self.head_extra = {}
        self.corrupt = False
        self.fail_upload = False
        self.after_upload = lambda: None

    def list_buckets(self):
        return {"Buckets": [{"Name": name} for name in self.buckets]}

    def get_bucket_versioning(self, **kwargs):
        return {"Status": self.versioning} if self.versioning else {}

    def get_bucket_policy(self, **kwargs):
        if self.policy:
            return {"Policy": "{}"}
        raise Missing("NoSuchBucketPolicy")

    def get_bucket_lifecycle_configuration(self, **kwargs):
        if self.lifecycle:
            return {"Rules": [{"Status": "Enabled"}]}
        raise Missing("NoSuchLifecycleConfiguration")

    def get_bucket_replication(self, **kwargs):
        raise Missing("ReplicationConfigurationNotFoundError")

    def get_bucket_tagging(self, **kwargs):
        raise Missing("NoSuchTagSet")

    def get_bucket_encryption(self, **kwargs):
        raise Missing("ServerSideEncryptionConfigurationNotFoundError")

    def get_object_tagging(self, **kwargs):
        return {"TagSet": self.tags}

    def get_bucket_acl(self, **kwargs):
        return self.acl

    def get_object_acl(self, **kwargs):
        return self.acl

    def get_paginator(self, _name):
        return self

    def paginate(self, Bucket):
        # Separate pages exercises complete listing, including newline keys.
        for key in self.buckets[Bucket]:
            yield {"Contents": [{"Key": key}]}

    def head_object(self, Bucket, Key):
        try:
            obj = self.buckets[Bucket][Key]
        except KeyError:
            raise Missing("404")
        return {"ContentLength": len(obj["body"]), "ETag": '"' + M.hashlib.md5(obj["body"]).hexdigest() + '"',
                "LastModified": "fixed", **obj["meta"], **self.head_extra}

    def get_object(self, Bucket, Key, IfMatch=None):
        head = self.head_object(Bucket, Key)
        if IfMatch and head["ETag"] != IfMatch:
            raise Missing("PreconditionFailed")
        return {**head, "Body": io.BytesIO(self.buckets[Bucket][Key]["body"])}

    def create_bucket(self, Bucket):
        self.buckets[Bucket] = {}

    def upload_fileobj(self, stream, bucket, key, ExtraArgs):
        self.uploads += 1
        if self.fail_upload:
            raise RuntimeError("interrupted")
        data = stream.read()
        self.buckets[bucket][key] = {"body": data + (b"corrupt" if self.corrupt else b""), "meta": ExtraArgs}
        self.after_upload()


def source():
    return S3({"photos": {
        "equipment/a.png": {"body": b"photo", "meta": {"ContentType": "image/png", "Metadata": {"sha256": "application-value"}}},
        "odd/../key\n.txt": {"body": b"text", "meta": {"ContentType": "text/plain", "CacheControl": "private", "Metadata": {}}},
    }, "empty-bucket": {}})


def migrate(src, dst, **kwargs):
    return M.copy_and_verify(src, dst, private_check=lambda *_: None, checkpoint=lambda *_: None, **kwargs)


class MigrationTests(unittest.TestCase):
    def test_complete_bytes_metadata_keys_and_empty_bucket(self):
        src, dst = source(), S3()
        before = copy.deepcopy(src.buckets)
        result = migrate(src, dst)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["total_bytes"], 9)
        self.assertEqual(dst.buckets, before)
        self.assertEqual(src.buckets, before)
        self.assertEqual(len(result["objects"]), 2)

    def test_dry_run_never_creates_or_uploads_target(self):
        dst = S3()
        result = migrate(source(), dst, dry_run=True)
        self.assertEqual(result["objects"], 2)
        self.assertEqual(dst.buckets, {})
        self.assertEqual(dst.uploads, 0)

    def test_resumed_copy_reverifies_and_skips_matching_objects(self):
        src, dst = source(), S3()
        migrate(src, dst)
        migrate(src, dst)
        self.assertEqual(dst.uploads, 2)
        dst.buckets["photos"]["equipment/a.png"]["body"] = b"tampered"
        migrate(src, dst)
        self.assertEqual(dst.uploads, 3)
        self.assertEqual(dst.buckets, src.buckets)

    def test_interrupted_copy_does_not_publish_acceptance_and_can_resume(self):
        dst = S3()
        dst.fail_upload = True
        with self.assertRaises(RuntimeError):
            migrate(source(), dst)
        dst.fail_upload = False
        self.assertEqual(migrate(source(), dst)["status"], "verified")

    def test_corrupt_target_fails_integrity(self):
        dst = S3()
        dst.corrupt = True
        with self.assertRaisesRegex(ValueError, "verification failed"):
            migrate(source(), dst)

    def test_source_mutation_fails_final_snapshot(self):
        src, dst = source(), S3()
        dst.after_upload = lambda: src.buckets["photos"].update({"new": {"body": b"new", "meta": {"Metadata": {}}}})
        with self.assertRaisesRegex(ValueError, "source changed"):
            migrate(src, dst)

    def test_private_access_failure_prevents_copy(self):
        dst = S3()
        with self.assertRaises(PermissionError):
            M.copy_and_verify(source(), dst, private_check=lambda *_: (_ for _ in ()).throw(PermissionError()), checkpoint=lambda *_: None)
        self.assertEqual(dst.buckets, {})

    def test_unknown_target_objects_are_not_deleted(self):
        dst = S3({"photos": {"unknown": {"body": b"retain", "meta": {"Metadata": {}}}}})
        with self.assertRaisesRegex(ValueError, "key set differs"):
            migrate(source(), dst)
        self.assertEqual(dst.buckets["photos"]["unknown"]["body"], b"retain")

    def test_unknown_target_bucket_rejected_before_copy(self):
        dst = S3({"unexpected": {}})
        with self.assertRaisesRegex(ValueError, "unexpected target bucket"):
            migrate(source(), dst)
        self.assertEqual(dst.uploads, 0)

    def test_unsupported_history_policy_or_tags_never_silently_lost(self):
        for field, value in (("versioning", "Enabled"), ("versioning", "Suspended"), ("policy", True), ("tags", [{"Key": "keep", "Value": "yes"}])):
            with self.subTest(field=field, value=value):
                src, dst = source(), S3()
                setattr(src, field, value)
                with self.assertRaises(ValueError):
                    migrate(src, dst)
                self.assertEqual(dst.uploads, 0)

    def test_public_or_custom_acl_rejected_before_target_writes(self):
        src, dst = source(), S3()
        src.acl['Grants'].append({'Grantee': {'Type': 'Group', 'URI': 'AllUsers'}, 'Permission': 'READ'})
        with self.assertRaisesRegex(ValueError, 'custom or public ACL'):
            migrate(src, dst)
        self.assertEqual(dst.buckets, {})

    def test_lifecycle_and_encryption_are_not_silently_lost(self):
        for field, value in (("lifecycle", True), ("head_extra", {"ServerSideEncryption": "AES256"}), ("head_extra", {"ObjectLockMode": "GOVERNANCE"})):
            src, dst = source(), S3()
            setattr(src, field, value)
            with self.assertRaises(ValueError):
                migrate(src, dst)
            self.assertEqual(dst.uploads, 0)

    def test_target_inventory_uses_only_supported_read_contract(self):
        dst = source()
        dst.policy = True
        dst.versioning = "unsupported_for_source"
        self.assertEqual(set(M.inventory(dst, source_rules=False)), {"photos", "empty-bucket"})

    def test_atomic_evidence_is_private(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            M.atomic_json(path, {"status": "copying"})
            M.atomic_json(path, {"status": "verified"})
            self.assertEqual(json.loads(path.read_text())["status"], "verified")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(path.with_suffix(".partial").exists())


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.proof = migrate(source(), S3())
        self.sha = "a" * 40
        self.proof.update(target_source=self.sha, target_volume_created_at="created", target_image_id="image-target",
                          frozen_writer_id="writer", source_writer_image_id="image-writer", source_container_id="source", source_image_id="image-source")
        self.records = {
            ("volume", "nexolab-central-object-storage-versitygw-data"): {"Name": "nexolab-central-object-storage-versitygw-data", "CreatedAt": "created"},
            ("image", "nexolab/object-storage:versitygw-v1.8.0"): {"Id": "image-target"},
            ("container", "writer"): {"Image": "image-writer", "State": {"Running": False}},
            ("container", "source"): {"Image": "image-source", "State": {"Running": True}, "Mounts": [{"Name": "nexolab-central-object-storage-data", "Destination": "/data"}]},
        }

    def validate(self):
        M.validate_proof(self.proof, self.sha, lambda kind, name: self.records[(kind, name)])

    def test_frozen_exact_images_volume_and_source_accept(self):
        self.validate()

    def test_running_writer_rejects_stale_manifest(self):
        self.records[("container", "writer")]["State"]["Running"] = True
        with self.assertRaisesRegex(ValueError, "remain frozen"):
            self.validate()

    def test_changed_target_volume_or_image_reject(self):
        for identity, key in ((("volume", "nexolab-central-object-storage-versitygw-data"), "CreatedAt"), (("image", "nexolab/object-storage:versitygw-v1.8.0"), "Id")):
            before = copy.deepcopy(self.records)
            self.records[identity][key] = "changed"
            with self.assertRaises(ValueError):
                self.validate()
            self.records = before

    def test_wrong_source_and_incomplete_integrity_evidence_reject(self):
        for field, value in (("target_source", "b" * 40), ("status", "copying"), ("total_bytes", 99)):
            before = copy.deepcopy(self.proof)
            self.proof[field] = value
            with self.assertRaises(ValueError):
                self.validate()
            self.proof = before

    def test_accepted_cutover_requires_live_target_and_retained_rollback(self):
        self.proof.update(cutover_verified=True, target_container_id="target")
        self.records[("container", "target")] = {"Image": "image-target", "State": {"Running": True}, "Mounts": [{"Name": "nexolab-central-object-storage-versitygw-data", "Destination": "/data"}]}
        self.records[("active_storage", "nexolab-central")] = self.records[("container", "target")]
        self.records[("image", "image-source")] = {"Id": "image-source"}
        self.records[("volume", "nexolab-central-object-storage-data")] = {"Name": "nexolab-central-object-storage-data"}
        self.records[("container", "writer")]["State"]["Running"] = True
        self.validate()
        M.validate_proof(self.proof, "b" * 40, lambda k, n: self.records[(k, n)], is_ancestor=lambda old, new: old == self.sha and new == "b" * 40)
        with self.assertRaisesRegex(ValueError, "lineage"):
            M.validate_proof(self.proof, "b" * 40, lambda k, n: self.records[(k, n)])
        self.records[("container", "target")]["State"]["Running"] = False
        with self.assertRaisesRegex(ValueError, "target storage identity"):
            self.validate()

    def test_already_mounted_target_cannot_bypass_canonical_guard(self):
        text = (ROOT / 'scripts/deploy-current-head-raspberry-pi.sh').read_text()
        start = text.index('LEGACY_OBJECT_STORAGE_VOLUME=')
        end = text.index('log "Rechecking deployment capacity', start)
        script = '''SCRIPT_DIR=/unused
REPO=/unused
TARGET_HEAD=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
docker() { if [[ "$*" == *"--format"* ]]; then echo nexolab-central-object-storage-versitygw-data; fi; return 0; }
python3() { echo PROOF_WAS_REQUIRED; return 23; }
fail() { exit 71; }
''' + text[start:end]
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 71)
        self.assertIn('PROOF_WAS_REQUIRED', result.stdout)

    def test_failed_writer_start_cannot_roll_storage_back(self):
        text = (ROOT / 'scripts/migrate-object-storage-raspberry-pi.sh').read_text()
        start = text.index('WRITER_RESUME_ATTEMPTED=1')
        end = text.index("echo 'Storage cutover verified", start)
        script = '''set -e
FROZEN=1
WRITER=writer
trap 'if [[ "$FROZEN" == 1 ]]; then echo UNSAFE_ROLLBACK; else echo TARGET_RETAINED; fi' EXIT
docker() { return 1; }
''' + text[start:end]
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('TARGET_RETAINED', result.stdout)
        self.assertNotIn('UNSAFE_ROLLBACK', result.stdout)

    def test_shell_scripts_parse_and_cli_guard_has_no_boto_dependency(self):
        for name in ("migrate-object-storage-raspberry-pi.sh", "deploy-current-head-raspberry-pi.sh"):
            result = subprocess.run(["bash", "-n", str(ROOT / "scripts" / name)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "authority.json"
            path.write_text('{"status":"copying"}')
            result = subprocess.run(["python3", str(ROOT / "scripts/deploy-object-storage-migration.py"), "--validate-proof", "--manifest", str(path), "--expected-target-source", self.sha], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("ModuleNotFoundError", result.stderr)


if __name__ == "__main__":
    unittest.main()
