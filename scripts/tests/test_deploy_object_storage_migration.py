from __future__ import annotations

import copy
import importlib.util
import io
import json
import subprocess
import tempfile
import time
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
        self.bucket_lock = False
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

    def get_object_lock_configuration(self, **kwargs):
        if self.bucket_lock:
            return {"ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled"}}
        raise Missing("ObjectLockConfigurationNotFoundError")

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

    def test_bucket_lock_rejected_even_without_retained_objects(self):
        for src in (source(), S3({"empty-locked": {}})):
            src.bucket_lock = True
            dst = S3()
            with self.assertRaisesRegex(ValueError, "get_object_lock_configuration"):
                migrate(src, dst)
            self.assertEqual(dst.buckets, {})
            self.assertEqual(dst.uploads, 0)

    def test_unreadable_bucket_lock_configuration_fails_closed(self):
        src, dst = source(), S3()
        def denied(**kwargs):
            raise Missing("AccessDenied")
        src.get_object_lock_configuration = denied
        with self.assertRaisesRegex(ValueError, "cannot establish absence"):
            migrate(src, dst)
        self.assertEqual(dst.buckets, {})

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

    def test_canonical_deployment_rejects_frozen_pre_cutover_authority(self):
        self.validate()  # Private wrapper pre-cutover validation still works.
        with self.assertRaisesRegex(ValueError, "completed cutover"):
            M.validate_proof(self.proof, self.sha, lambda kind, name: self.records[(kind, name)],
                             require_cutover=True)

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
        M.validate_proof(self.proof, self.sha, lambda k, n: self.records[(k, n)], require_cutover=True)
        M.validate_proof(self.proof, "b" * 40, lambda k, n: self.records[(k, n)], is_ancestor=lambda old, new: old == self.sha and new == "b" * 40)
        with self.assertRaisesRegex(ValueError, "lineage"):
            M.validate_proof(self.proof, "b" * 40, lambda k, n: self.records[(k, n)])
        self.records[("container", "target")]["State"]["Running"] = False
        with self.assertRaisesRegex(ValueError, "target storage identity"):
            self.validate()

    def test_already_mounted_target_cannot_bypass_canonical_guard(self):
        text = (ROOT / 'scripts/deploy-current-head-raspberry-pi.sh').read_text()
        self.assertIn('--validate-proof --require-cutover', text)
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

    def test_source_preflight_cannot_mix_new_checkout_with_old_target(self):
        text = (ROOT / 'scripts/migrate-object-storage-raspberry-pi.sh').read_text()
        start = text.index('# Preflight synchronizes main.')
        end = text.index('STAMP=', start)
        script = 'TARGET=old\ngit() { echo new; }\n' + text[start:end] + '\necho UNSAFE_CONTINUATION\n'
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('HEAD changed', result.stderr)
        self.assertNotIn('UNSAFE_CONTINUATION', result.stdout)

    def image_preparation(self, present, version="versitygw version v1.8.0", bundle_present=False, offline=False):
        text = (ROOT / 'scripts/migrate-object-storage-raspberry-pi.sh').read_text()
        start = text.index('nexolab_prepare_migration_image()')
        end = text.index('VOLUME=', start)
        script = 'OFFLINE_SOURCE_REF=' + ('accepted' if offline else '') + '\n' + '''set -e
docker() {
  if [[ "$1 $2" == "image inspect" ]]; then
    if [[ "$*" == *".Os"* ]]; then echo linux/arm64;
    elif [[ "$*" == *"Entrypoint"* ]]; then echo '["/usr/local/bin/versitygw"]';
    elif [[ "$*" == *".Id"* ]]; then echo sha256:accepted;
    elif [[ "$*" == *"-arm64"* ]]; then return ''' + ("0" if bundle_present else "1") + ''';
    else return ''' + ("0" if present else "1") + ''';
    fi
  elif [[ "$1 $2" == "image tag" ]]; then echo "TAG_VERIFIED:$3:$4";
  elif [[ "$1" == build ]]; then echo BUILD_REQUIRED;
  elif [[ "$1" == run ]]; then echo "''' + version + '''";
  fi
}
''' + text[start:end]
        return subprocess.run(['bash', '-c', script], capture_output=True, text=True)

    def test_preloaded_offline_image_skips_build_and_checks_version(self):
        result = self.image_preparation(True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('BUILD_REQUIRED', result.stdout)
        bad = self.image_preparation(True, "versitygw version v1.7.0")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn('must report', bad.stderr)

    def test_actual_offline_bundle_tag_is_verified_and_retagged_without_build(self):
        result = self.image_preparation(False, bundle_present=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('BUILD_REQUIRED', result.stdout)
        self.assertIn('TAG_VERIFIED:sha256:accepted:nexolab/object-storage:versitygw-v1.8.0', result.stdout)
        bad = self.image_preparation(False, version="versitygw version v1.7.0", bundle_present=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertNotIn('TAG_VERIFIED', bad.stdout)

    def test_offline_missing_image_fails_without_build(self):
        result = self.image_preparation(False, offline=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('BUILD_REQUIRED', result.stdout)
        self.assertIn('requires a verified preloaded', result.stderr)

    def test_missing_image_uses_pinned_build(self):
        result = self.image_preparation(False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('BUILD_REQUIRED', result.stdout)

    def test_final_deployment_preserves_verified_preloaded_storage_image(self):
        text = (ROOT / 'scripts/deploy-current-head-raspberry-pi.sh').read_text()
        start = text.index('nexolab_activate_central()')
        end = text.index('log "Starting real-hardware edge stack"', start)
        script = '''set -e
MIGRATION_AUTHORITY_VALIDATED=1
CENTRAL_ENV=/unused
CENTRAL_COMPOSE_ARGS=(-f unused)
SCRIPT_DIR=/unused
REPO=/unused
TARGET_HEAD=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
docker() {
  echo "$*" >> "$CALLS"
  if [[ "$*" == *"config --format json"* ]]; then
    echo \'{"services":{"minio":{"build":"storage"},"telemetry-service":{"build":"telemetry"},"extra":{"build":"extra"},"db":{"image":"postgres"}}}\'
  fi
}
python3() {
  if [[ "$1" == -c ]]; then command python3 "$@";
  else echo PROOF_RECHECKED;
  fi
}
''' + text[start:end]
        with tempfile.TemporaryDirectory() as temp:
            calls = Path(temp) / 'calls'
            result = subprocess.run(['bash', '-c', 'CALLS="' + str(calls) + '"\n' + script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            recorded = calls.read_text()
            self.assertIn('build telemetry-service extra', recorded)
            self.assertNotIn('build minio', recorded)
            self.assertNotIn('--build', recorded)
            self.assertIn('up -d --no-build --pull never --wait', recorded)
            self.assertIn('PROOF_RECHECKED', result.stdout)

    def test_offline_source_selection_never_fetches_and_rejects_cached_drift(self):
        text = (ROOT / 'scripts/deploy-current-head-raspberry-pi.sh').read_text()
        start = text.index('  if [[ "$OFFLINE_SOURCE_SELECTION" == 1 ]]; then', text.index('if [[ "$SOURCE_SELECTION_CHECK_ONLY" == "1" ]]; then'))
        end = text.index('  resolve_deployed_source_authority', start)
        for cached in ("a" * 40, "b" * 40):
            script = '''OFFLINE_SOURCE_SELECTION=1
REQUESTED_SOURCE_REF=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
log() { :; }
fail() { exit 71; }
git() {
  if [[ "$*" == "rev-parse origin/main" ]]; then echo ''' + cached + ''';
  elif [[ "$*" == "rev-parse HEAD" ]]; then echo aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa;
  elif [[ "$*" == "branch --show-current" ]]; then echo main;
  else echo NETWORK_OR_CHECKOUT_MUTATION; return 99;
  fi
}
''' + text[start:end]
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0 if cached == "a" * 40 else 71)
            self.assertNotIn('NETWORK_OR_CHECKOUT_MUTATION', result.stdout)

    def test_offline_migration_hands_off_without_networked_final_deployment(self):
        text = (ROOT / 'scripts/migrate-object-storage-raspberry-pi.sh').read_text()
        start = text.index('if [[ -n "$OFFLINE_SOURCE_REF" ]]; then\n  echo')
        script = 'OFFLINE_SOURCE_REF=accepted\n' + text[start:]
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('OFFLINE_STORAGE_CUTOVER_VERIFIED', result.stdout)
        self.assertIn('update remains pending', result.stdout)
        self.assertNotIn('Storage cutover verified;', result.stdout)

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


class SharedLockTests(unittest.TestCase):
    def test_inherited_canonical_lock_works_but_independent_operation_is_blocked(self):
        library = ROOT / 'scripts/lib/deployment-lock.sh'
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / 'canonical.lock'
            ready = Path(temp) / 'ready'
            holder_script = f'''set -e
source "{library}"
nexolab_acquire_deployment_lock "{lock}"
export NEXOLAB_INHERITED_DEPLOYMENT_LOCK_FD=9
bash -c 'source "{library}"; nexolab_acquire_deployment_lock "{lock}"; echo CHILD_VALIDATED'
touch "{ready}"
read -r _
'''
            holder = subprocess.Popen(['bash', '-c', holder_script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 3
                while not ready.exists() and holder.poll() is None and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(ready.exists())
                independent = subprocess.run(['bash', '-c', f'source "{library}"; nexolab_acquire_deployment_lock "{lock}"'], capture_output=True, text=True)
                self.assertEqual(independent.returncode, 75)
                stdout, stderr = holder.communicate('release\n', timeout=3)
                self.assertEqual(holder.returncode, 0, stderr)
                self.assertIn('CHILD_VALIDATED', stdout)
                after = subprocess.run(['bash', '-c', f'source "{library}"; nexolab_acquire_deployment_lock "{lock}"'], capture_output=True, text=True)
                self.assertEqual(after.returncode, 0, after.stderr)
            finally:
                if holder.poll() is None:
                    holder.kill()
                    holder.communicate()

    def test_claimed_inheritance_without_correct_descriptor_fails_closed(self):
        library = ROOT / 'scripts/lib/deployment-lock.sh'
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(['bash', '-c', f'export NEXOLAB_INHERITED_DEPLOYMENT_LOCK_FD=9; source "{library}"; nexolab_acquire_deployment_lock "{temp}/canonical.lock"'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 64)


if __name__ == "__main__":
    unittest.main()
