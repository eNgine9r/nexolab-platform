from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_forward_deployment_recovery import fixture, recovery

SCRIPT = Path(__file__).resolve().parents[1] / "deploy-complete-partial-frontends.py"
spec = importlib.util.spec_from_file_location("completion", SCRIPT)
completion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(completion)


class CompletionTests(unittest.TestCase):
    def test_check_data_uses_real_acquisition_gate_with_current_worker_baseline(self):
        snapshot, context = fixture()
        for field, (identifier, image) in completion.EXPECTED_COMPONENTS.items():
            snapshot[field]['container_id'], snapshot[field]['image_id'] = identifier, image
            snapshot[field]['local_image_id'] = image
        agent = snapshot['device_agent']
        agent['expected_bus_workers'] = agent['active_bus_workers'] = 3
        op = completion.Operations.__new__(completion.Operations)
        op.context, op.recovery = context, recovery
        op.live_high_water, op.before, op.input_hashes = None, {}, {}
        op.footprint = lambda: {}
        health = {'status': 'ok', 'mqtt_connected': True, 'queue_depth': 0,
                  'samples_total': 100, 'acquisition': {'scheduler': {
                      'expected_bus_workers': 3, 'active_bus_workers': 3, 'workers_healthy': True}}}
        later = copy.deepcopy(health)
        later['samples_total'] = 101
        with patch.object(recovery, 'collect_runtime_snapshot', return_value=snapshot), \
                patch.object(recovery, '_partial_http', side_effect=[health, later]), \
                patch.object(recovery.time, 'sleep'):
            op.check_data()

    def test_backend_gate_accepts_old_frontend_without_weakening_full_gate(self):
        snapshot, context = fixture()
        snapshot["dashboard"]["working_directory"] = "/old/frontend"
        recovery.validate_runtime_data_snapshot(snapshot, context)
        with self.assertRaisesRegex(recovery.RecoveryFailure, "active Dashboard"):
            recovery.validate_runtime_snapshot(snapshot, context)

    def test_completion_acquisition_gate_rejects_changed_worker_plan(self):
        health = {'status': 'ok', 'mqtt_connected': True, 'queue_depth': 0,
                  'samples_total': 100, 'acquisition': {'scheduler': {
                      'expected_bus_workers': 2, 'active_bus_workers': 2, 'workers_healthy': True}}}
        with patch.object(recovery, '_partial_http', return_value=health):
            with self.assertRaisesRegex(recovery.RecoveryFailure, 'not operationally healthy'):
                recovery.check_partial_acquisition({'agent_health': [{
                    'expected_bus_workers': completion.EXPECTED_BUS_WORKERS}]})

    def test_check_data_rejects_later_live_high_water_regression(self):
        snapshot, context = fixture()
        op = completion.Operations.__new__(completion.Operations)
        op.context, op.recovery, op.live_high_water = context, recovery, 102
        with patch.object(recovery, 'collect_runtime_snapshot', return_value=snapshot):
            with self.assertRaisesRegex(completion.CompletionFailure, 'high-water regressed'):
                op.check_data()

    def test_data_gate_rejects_high_water_regression_and_schema_drift(self):
        snapshot, context = fixture()
        for path, field, value in (("device_agent", "sqlite", {"quick_check": "ok", "outbound_queue_count": 0, "outbound_queue_high_water": 99}),
                                   ("postgres", "schema_head", "wrong")):
            bad = copy.deepcopy(snapshot)
            bad[path][field] = value
            with self.assertRaises(recovery.RecoveryFailure):
                recovery.validate_runtime_data_snapshot(bad, context)

    def test_pair_failure_restores_both_and_never_publishes(self):
        operations = Mock()
        operations.activate.side_effect = [None, ValueError("failed")]
        with self.assertRaises(ValueError):
            completion.handoff(operations)
        self.assertEqual([c.args[0] for c in operations.restore.call_args_list], ["protected", "lan"])
        operations.publish.assert_not_called()
        operations.verify_restored.assert_called_once()

    def test_data_failure_after_handoff_restores_pair_and_gateway(self):
        operations = Mock()
        operations.verify_target.side_effect = ValueError("data changed")
        with self.assertRaises(ValueError):
            completion.handoff(operations)
        operations.restore.assert_any_call("protected")
        operations.restore.assert_any_call("lan")
        operations.publish.assert_not_called()

    def test_restore_failure_is_reported_and_other_frontend_still_restored(self):
        operations = Mock()
        operations.activate.side_effect = ValueError("failed")
        operations.restore.side_effect = ValueError("rollback failed")
        with self.assertRaisesRegex(completion.CompletionFailure, "rollback unverified"):
            completion.handoff(operations)
        operations.publish.assert_not_called()

    def test_success_publishes_only_after_pair_and_data_verification(self):
        operations = Mock()
        completion.handoff(operations)
        names = [c[0] for c in operations.mock_calls]
        self.assertEqual(names, ["mark_started", "activate", "activate", "verify_target", "publish"])

    def test_uncertain_publication_keeps_verified_target_pair(self):
        operations = Mock()
        operations.publish.side_effect = OSError("fsync failed after rename")
        operations.publication_exists.return_value = True
        with self.assertRaisesRegex(completion.CompletionFailure, "publication uncertain"):
            completion.handoff(operations)
        operations.restore.assert_not_called()

    def test_failed_publication_before_write_restores_pair(self):
        operations = Mock()
        operations.publish.side_effect = OSError("create failed")
        operations.publication_exists.return_value = False
        with self.assertRaises(OSError):
            completion.handoff(operations)
        self.assertEqual(operations.restore.call_count, 2)

    def test_actual_switch_restarts_required_gateway_after_protected_frontend(self):
        op = completion.Operations.__new__(completion.Operations)
        op.audit = Path('/private/audit')
        op.builds = {'protected': 'target-build'}
        op.run, op.probe, op.gateway = Mock(), Mock(), Mock()
        op.switch('protected', True)
        commands = [c.args for c in op.run.call_args_list]
        self.assertEqual(commands[-2:], [('systemctl', 'start', 'nexolab-external-frontend.service'),
                                       ('systemctl', 'start', 'nexolab-external-nginx.service')])
        op.probe.assert_called_once_with('protected', completion.TARGET, 'target-build')
        op.gateway.require_gateway_active.assert_called_once()

    def test_gateway_failure_during_restore_cannot_report_success(self):
        op = completion.Operations.__new__(completion.Operations)
        op.audit = Path('/private/audit')
        op.builds = {'protected': 'target-build'}
        op.run, op.probe, op.gateway = Mock(), Mock(), Mock()
        op.gateway.require_gateway_active.side_effect = ValueError('unsafe gateway')
        with self.assertRaises(ValueError):
            op.restore('protected')
        op.probe.assert_called_once_with('protected', *completion.OLD_IDENTITIES['protected'])

    def test_wrong_latest_attempt_or_quiesced_image_is_rejected(self):
        metadata = dict(completion.EXPECTED_METADATA)
        quiesce = dict(completion.EXPECTED_QUIESCE)
        completion.validate_latest_lineage(metadata, quiesce)
        for doc, key in ((metadata, "deployment_evidence_id"), (quiesce, "image_id")):
            before = doc[key]
            doc[key] = "wrong"
            with self.assertRaises(completion.CompletionFailure):
                completion.validate_latest_lineage(metadata, quiesce)
            doc[key] = before

    def test_container_or_volume_drift_is_rejected(self):
        before = {"containers": [{"id": "first"}], "volumes": [{"Name": "data"}]}
        completion.require_unchanged(before, copy.deepcopy(before))
        for field in before:
            after = copy.deepcopy(before)
            after[field] = []
            with self.assertRaises(completion.CompletionFailure):
                completion.require_unchanged(before, after)

    def test_no_full_installer_or_database_restore_commands(self):
        text = SCRIPT.read_text()
        for forbidden in ("docker compose", "docker stop", "--continue-partial-activation", "restore-current", "current.json"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
