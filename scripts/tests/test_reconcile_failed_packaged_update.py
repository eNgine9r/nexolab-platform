"""Fail-closed regression tests for bounded #1384 recovery; never contact live site."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "reconcile-failed-packaged-update.py"
SPEC = importlib.util.spec_from_file_location("nexolab_reconcile_1384", SCRIPT)
assert SPEC and SPEC.loader
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)

def current():
    return {
        "source_commit": recovery.OLD,
        "bundle_id": recovery.OLD_BUNDLE,
        "deployment_authority": "validated_package",
        "health": "verification_failed",
        "runtime_state_known": False,
        "last_operation_id": recovery.FAILED,
        "schema_head": recovery.SCHEMA,
        "edge_hardware_required": True,
        "hardware_contract": {"status":"verified", "device_mode":"modbus",
                              "observed_buses":["serial-one"], "bus_bindings":[{"bus_id":"main","serial_device":"serial-one"}]},
        "release": "old-release", "runtime_mode": "lan",
        "platform":"linux/arm64"
    }

def failed():
    return {
        "id": recovery.FAILED, "status": "failed", "action": "update",
        "phase": "verifying_runtime", "target_commit": recovery.NEW,
        "result_code": "VersionManagerFailure",
        "safe_message": "Device Agent RS-485 topology changed during version operation",
        "backup_evidence_id": recovery.FAILED + "-postgresql.dump",
        "completed_phases": ["verifying_package", "creating_backup", "applying_update"],
    }

def target():
    return {
        "source_commit":recovery.NEW, "platform":"linux/arm64",
        "version_management":{"bundle_id":recovery.NEW_BUNDLE,
                              "database_schema":{"head":recovery.SCHEMA}},
        "dashboard":{"auth_provider":"local"},
        "external_frontend":{"source_commit":recovery.NEW,"origin":"https://nexolab-edge-01.tail7f9b04.ts.net"},
        "bundle_version":"target-release", "created_at":"fixture",
    }

class GuardedRecoveryTests(unittest.TestCase):
    def test_only_exact_failed_operation_is_eligible(self):
        recovery.validate_old_authority(current(), failed(), target())
        broken = current()
        broken["health"] = "ready"
        with self.assertRaisesRegex(recovery.RecoveryBlocked, "CURRENT_IS_NOT_EXPECTED"):
            recovery.validate_old_authority(broken, failed(), target())
        broken = failed()
        broken["safe_message"] = "unrelated failure"
        with self.assertRaisesRegex(recovery.RecoveryBlocked, "FAILED_OPERATION_NOT_EXACT"):
            recovery.validate_old_authority(current(), broken, target())
        broken = target()
        broken["external_frontend"]["source_commit"] = recovery.OLD
        with self.assertRaisesRegex(recovery.RecoveryBlocked, "TARGET_OR_HARDWARE"):
            recovery.validate_old_authority(current(), failed(), broken)

    def test_exact_six_runtime_image_digests_required(self):
        m = {"images":[{"id":k, "identity":{"runtime_digests":["sha256:"+k]}}
                      for k in recovery.CONTAINERS]}
        def inspect(args,**kw):
            name = args[-1]
            image = next(k for k,v in recovery.CONTAINERS.items() if v==name)
            return "sha256:"+image
        with patch.object(recovery,"read_command",side_effect=inspect) as proc:
            recovery.compare_images(m)
            self.assertEqual(proc.call_count,6)
        with patch.object(recovery,"read_command",return_value="sha256:unrelated"):
            with self.assertRaisesRegex(recovery.RecoveryBlocked,"IMAGE_IDENTITY_CHANGED"):
                recovery.compare_images(m)

    def test_versitygw_health_contract_never_requires_docker_healthcheck(self):
        calls = []
        def check(argv, **kwargs):
            calls.append(argv)
            if argv[1] == "inspect" and argv[-1] == recovery.CONTAINERS["object-storage"]:
                self.assertIn("State.Running", argv[-2])
                return "true"
            if argv[1] == "exec":
                self.assertEqual(argv[2], recovery.CONTAINERS["telemetry-service"])
                self.assertEqual(argv[3:5], ["python3", "-c"])
                self.assertIn("HTTPConnection('minio', 9000, timeout=5)", argv[5])
                self.assertIn("connection.request('GET', '/health')", argv[5])
                self.assertIn("getresponse().status != 200", argv[5])
                self.assertIn("timeout=5", argv[5])
                self.assertEqual(kwargs.get("timeout"), 12)
                return "READY"
            return "healthy"
        with patch.object(recovery, "read_command", side_effect=check):
            recovery.verify_runtime_container_health()
        self.assertEqual(len(calls), 7)  # five Docker checks + running + VersityGW GET
        health = [argv for argv in calls if "State.Health.Status" in str(argv)]
        self.assertEqual(len(health), 5)
        self.assertNotIn(recovery.CONTAINERS["object-storage"], [argv[-1] for argv in health])

    def test_versitygw_fails_closed_if_stopped_unready_or_probe_failed(self):
        for state, expected in [
            ("stopped", "OBJECT_STORAGE_NOT_RUNNING"),
            ("unexpected_response", "OBJECT_STORAGE_NOT_READY"),
            ("http_404_or_500", "READ_ONLY_CHECK_FAILED"),
            ("timeout", "READ_ONLY_CHECK_FAILED"),
        ]:
            with self.subTest(state=state):
                def check(argv, **kwargs):
                    if argv[-1] == recovery.CONTAINERS["object-storage"]:
                        return "false" if state == "stopped" else "true"
                    if argv[1] == "exec":
                        if state in ("http_404_or_500", "timeout"):
                            raise recovery.RecoveryBlocked("READ_ONLY_CHECK_FAILED")
                        return "NOT_READY"
                    return "healthy"
                with patch.object(recovery, "read_command", side_effect=check):
                    with self.assertRaisesRegex(recovery.RecoveryBlocked, expected):
                        recovery.verify_runtime_container_health()

    def test_other_containers_still_require_healthy(self):
        for bad in ("starting", "unhealthy"):
            with self.subTest(status=bad):
                def check(argv, **kwargs):
                    return bad if argv[-1] == recovery.CONTAINERS["dashboard"] else "healthy"
                with patch.object(recovery, "read_command", side_effect=check):
                    with self.assertRaisesRegex(recovery.RecoveryBlocked, "CONTAINER_NOT_HEALTHY_dashboard"):
                        recovery.verify_runtime_container_health()
        with patch.object(recovery, "read_command", side_effect=recovery.RecoveryBlocked("READ_ONLY_CHECK_FAILED")):
            with self.assertRaisesRegex(recovery.RecoveryBlocked, "READ_ONLY_CHECK_FAILED"):
                recovery.verify_runtime_container_health()

    def test_invalid_hardware_or_schema_blocks_even_when_images_match(self):
        native=MagicMock()
        native.verify_real_hardware_runtime.return_value={
            "device_mode":"simulator","observed_buses":["serial-one"],
            "bus_bindings":[{"bus_id":"main","serial_device":"serial-one"}]
        }
        with patch.object(recovery,"compare_images"),patch.object(recovery,"read_command",return_value=recovery.SCHEMA+" (head)"):
            with self.assertRaisesRegex(recovery.RecoveryBlocked,"HARDWARE_CHANGED_device_mode"):
                recovery.verify_runtime(native,argparse.Namespace(),current(),target())
        native.verify_real_hardware_runtime.return_value=current()["hardware_contract"]
        with patch.object(recovery,"compare_images"),patch.object(recovery,"read_command",return_value="20260202_0001 (head)"):
            native.require_exact_alembic_head.side_effect=ValueError("mismatched DB")
            with self.assertRaisesRegex(ValueError,"mismatched DB"):
                recovery.verify_runtime(native,argparse.Namespace(),current(),target())

    def test_backup_requires_owner_proof_and_exact_sha(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            backup_dir=root/"backups";backup_dir.mkdir()
            file=backup_dir/(recovery.FAILED+"-postgresql.dump")
            with file.open("wb") as f:f.truncate(992743918)  # sparse fixture
            file.chmod(0o600)
            audit=root/"audit.json"
            audit.write_text(json.dumps({
                "kind":"nexolab_1384_read_only_recovery_preflight",
                "status":"READ_ONLY_EVIDENCE_CAPTURED",
                "all_read_only_gates_pass":True,
                "archive_list_entries":611,
                "backup_sha256":recovery.BACKUP_SHA,
            }))
            with patch.object(recovery,"AUDIT",audit),patch.object(recovery,"BACKUP_DIR",backup_dir),patch.object(recovery,"sha256",side_effect=lambda p: recovery.AUDIT_SHA256 if p==audit else recovery.BACKUP_SHA):
                self.assertEqual(recovery.confirm_backup()["bytes"],992743918)
                file.chmod(0o644)
                with self.assertRaisesRegex(recovery.RecoveryBlocked,"PROTECTED_BACKUP_CHANGED"):
                    recovery.confirm_backup()

    def _transaction(self, *, fail_second_validation=False, uncertain_commit=False):
        root_temp=tempfile.TemporaryDirectory()
        self.addCleanup(root_temp.cleanup)
        root=Path(root_temp.name)
        (root/"worker.lock").touch()
        (root/"update-plane.lock").touch()
        (root/"current.json").write_text(json.dumps(current()))
        (root/"operations").mkdir()
        (root/"operation-evidence").mkdir()
        (root/"operations"/(recovery.FAILED+".json")).write_text(json.dumps(failed()))
        args=argparse.Namespace(root=root,backup_dir=root/"backups",central_env=root/"central.env",
                                edge_env=root/"edge.env",execute=True,
                                approve="RECONCILE-FAILED-"+recovery.FAILED)
        native=MagicMock()
        native.assert_no_active_version_operation=MagicMock()
        native.now.return_value="2026-10-14T20:00:00Z"
        def write_atomic(p, v):
            p.write_text(json.dumps(v))
            if uncertain_commit and p.name == "current.json":
                raise OSError("simulated post-rename durability issue")
        native.atomic_json.side_effect=write_atomic
        frontend=MagicMock()
        frontend.enabled=True
        frontend.was_active=True
        frontend.original_identity={"source_commit":recovery.OLD}
        frontend.metadata=target()["external_frontend"]
        native.protected_frontend_transaction.return_value=frontend
        vol=[{"name":"persistent","created_at":"original"}]
        def check(*args,**kwargs):
            check.n += 1
            if fail_second_validation and check.n==1:
                raise recovery.RecoveryBlocked("HARDWARE_CHANGED_bus_bindings")
            return vol,current()["hardware_contract"]
        check.n=0
        with (
            patch.object(recovery.os,"geteuid",return_value=0),
            patch.object(recovery,"inspect_exact_site",return_value=(
                current(),target(),root/"catalog"/recovery.NEW_BUNDLE,
                {"sha256":recovery.BACKUP_SHA},vol,current()["hardware_contract"]
            )),
            patch.object(recovery,"verify_runtime",side_effect=check),
        ):
            if fail_second_validation:
                with self.assertRaisesRegex(recovery.RecoveryBlocked,"HARDWARE_CHANGED"):
                    recovery.reconcile(args,native)
            elif uncertain_commit:
                with self.assertRaisesRegex(OSError, "post-rename"):
                    recovery.reconcile(args,native)
            else:
                result=recovery.reconcile(args,native)
                self.assertEqual(result["status"],"succeeded")
        return root,frontend,native

    def test_proof_first_then_atomic_authority_commit(self):
        root,frontend,native=self._transaction()
        now=json.loads((root/"current.json").read_text())
        self.assertEqual(now["source_commit"],recovery.NEW)
        self.assertEqual(now["previous_bundle_id"],recovery.OLD_BUNDLE)
        self.assertEqual(now["last_operation_id"],recovery.RECOVERY_ID)
        self.assertTrue(now["runtime_state_known"])
        old=json.loads((root/"operations"/(recovery.FAILED+".json")).read_text())
        self.assertEqual(old["status"],"failed")
        self.assertEqual(json.loads((root/"operation-evidence"/recovery.RECOVERY_ID/"recovery-result.json").read_text())["status"],"succeeded")
        frontend.prepare.assert_called_once()
        frontend.activate.assert_called_once()
        frontend.rollback.assert_not_called()
        native.verify_device_agent_progress.assert_called_once_with(observation_seconds=60)

    def test_post_frontend_hardware_failure_rolls_back_and_preserves_unknown(self):
        root,frontend,native=self._transaction(fail_second_validation=True)
        now=json.loads((root/"current.json").read_text())
        self.assertEqual(now["source_commit"],recovery.OLD)
        self.assertIs(now["runtime_state_known"],False)
        self.assertEqual(now["health"],"verification_failed")
        frontend.rollback.assert_called_once()
        journal=json.loads((root/"operation-evidence"/recovery.RECOVERY_ID/"recovery-result.json").read_text())
        self.assertEqual(journal["status"],"failed")
        self.assertEqual(json.loads((root/"operations"/(recovery.FAILED+".json")).read_text())["status"],"failed")

    def test_post_replace_error_does_not_roll_back_https_after_new_authority_published(self):
        root,frontend,native=self._transaction(uncertain_commit=True)
        state=json.loads((root/"current.json").read_text())
        self.assertEqual(state["source_commit"],recovery.NEW)
        frontend.rollback.assert_not_called()
        result=json.loads((root/"operation-evidence"/recovery.RECOVERY_ID/"recovery-result.json").read_text())
        self.assertEqual(result["status"],"commit_uncertain_operator_review_required")

    def test_owner_approval_required_before_any_mutation(self):
        args=argparse.Namespace(root=Path("/tmp"),backup_dir=Path("/tmp"),
                                execute=False,approve="")
        with patch.object(recovery.os,"geteuid",return_value=0):
            with self.assertRaisesRegex(recovery.RecoveryBlocked,"OWNER_EXPLICIT_APPROVAL_REQUIRED"):
                recovery.reconcile(args,MagicMock())

if __name__=="__main__":
    unittest.main()

class RealNativeHardwareContractTests(unittest.TestCase):
    """Exercise the real native worker contract, not a MagicMock."""

    @staticmethod
    def native_module():
        native_path = SCRIPT.with_name("nexolab-version-manager.py")
        spec = importlib.util.spec_from_file_location("nexolab_real_worker_contract", native_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_native_hardware_contract_has_mandatory_edge_and_no_skip_flag(self):
        native = self.native_module()
        with tempfile.TemporaryDirectory() as d:
            edge = Path(d) / "edge.env"
            edge.write_text(
                "RS485_HOST_DEVICE=/dev/serial/by-id/usb-test-main\n"
                "HARDWARE_DEVICE_MODE=xjp60d\n"
            )
            args = recovery.parser().parse_args([
                "--central-env", str(Path(d) / "central.env"),
                "--edge-env", str(edge),
            ])
            self.assertIs(args.skip_edge, False)
            self.assertEqual(args.approve, "")
            self.assertFalse(args.execute)
            with patch.object(native, "parse_env_file", return_value={
                "RS485_HOST_DEVICE": "/dev/serial/by-id/usb-test-main",
                "HARDWARE_DEVICE_MODE": "xjp60d",
            }):
                contract = native.expected_real_hardware_contract(args)
                self.assertEqual(contract["container_serial_device"], "/host/dev/serial/by-id/usb-test-main")
                args.skip_edge = True
                with self.assertRaisesRegex(native.VersionManagerFailure, "requires the real edge runtime"):
                    native.expected_real_hardware_contract(args)

    def test_recovery_runtime_probes_real_modbus_hardware_worker(self):
        native = self.native_module()
        args = recovery.parser().parse_args([
            "--central-env", "/fixtures/central.env",
            "--edge-env", "/fixtures/edge.env",
        ])
        serial = "/host/dev/serial/by-id/usb-test-main"
        health = {
            "status": "ok", "device_mode": "modbus",
            "acquisition": {
                "rs485_buses": [{"bus_id": "rs485-main", "serial_device": serial,
                                 "device_path_present": True}],
                "request_series": [{"bus": "rs485-main", "outcome": "success",
                                    "requests_total": 3}],
            },
        }
        with (
            patch.object(native, "parse_env_file", return_value={
                "RS485_HOST_DEVICE": "/dev/serial/by-id/usb-test-main",
                "HARDWARE_DEVICE_MODE": "xjp60d",
            }),
            patch.object(native, "read_local_json", return_value=health),
            patch.object(native, "capture_volume_identities", return_value=[{"name":"expected-volume"}]),
            patch.object(recovery, "compare_images"),
            patch.object(recovery, "read_command", side_effect=lambda argv, **kw:
                         recovery.SCHEMA + " (head)" if "alembic" in argv else
                         "true" if argv[-1] == recovery.CONTAINERS["object-storage"] else
                         "READY" if argv[1] == "exec" else "healthy"),
        ):
            expected_hardware = native.verify_real_hardware_runtime(args)
            old = current()
            old["hardware_contract"] = expected_hardware
            volumes, observed = recovery.verify_runtime(native, args, old, target())
        self.assertEqual(observed, expected_hardware)
        self.assertEqual(volumes, [{"name": "expected-volume"}])
        self.assertGreater(observed["successful_requests"], 0)
