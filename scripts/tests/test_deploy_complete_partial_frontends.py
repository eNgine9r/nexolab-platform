from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_forward_deployment_recovery import fixture, recovery

SCRIPT = Path(__file__).resolve().parents[1] / "deploy-complete-partial-frontends.py"
spec = importlib.util.spec_from_file_location("completion", SCRIPT)
completion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(completion)
adopter_spec = importlib.util.spec_from_file_location(
    "completion_adopter", SCRIPT.parent / "nexolab-adopt-source-deployment.py")
adopter = importlib.util.module_from_spec(adopter_spec)
adopter_spec.loader.exec_module(adopter)


class CompletionTests(unittest.TestCase):
    def test_actual_lan_start_receives_handoff_time_and_owner_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            op = completion.Operations.__new__(completion.Operations)
            op.audit = Path(root)
            op.identity_path = Path(root) / 'identity.json'
            op.candidate_identity_path = Path(root) / 'candidate-identity.json'
            op.builds = {'lan': 'target-build'}
            op.owner = SimpleNamespace(pw_uid=0, pw_gid=0)
            op.recovery, op.probe, op.gateway = recovery, Mock(), Mock()
            with patch.object(completion.os, 'chown') as chown:
                op.write_identity(None)
                self.assertIsNone(json.loads(op.candidate_identity_path.read_text())['deployed_at'])
                self.assertFalse(op.identity_path.exists())
                observed = []
                op.run = Mock(side_effect=lambda *args: observed.append(json.loads(op.identity_path.read_text()))
                              if args == ('systemctl', 'start', completion.UNITS['lan']) else '')
                before = completion.datetime.now(completion.timezone.utc)
                op.activate('lan')
                after = completion.datetime.now(completion.timezone.utc)
                self.assertEqual(observed[0]['deployed_at'], op.frontend_activated_at)
                self.assertLessEqual(before, completion.datetime.fromisoformat(op.frontend_activated_at))
                self.assertLessEqual(completion.datetime.fromisoformat(op.frontend_activated_at), after)
                self.assertEqual(chown.call_count, 2)
                chown.assert_called_with(op.identity_path, 0, 0)
                op.restore('lan')
                self.assertEqual(chown.call_count, 2)  # Old unit retains its separate original identity.

    def test_target_verification_rejects_missing_live_activation_time(self):
        snapshot, context = fixture()
        op = completion.Operations.__new__(completion.Operations)
        op.context, op.recovery, op.check_data = context, recovery, Mock(return_value=snapshot)
        op.releases = {'lan': context['release_dir'], 'protected': Path('/protected')}
        op.builds, op.frontend_activated_at = {'lan': 'build-1', 'protected': 'protected-build'}, '2026-10-10T21:10:00+00:00'
        op.run = Mock(side_effect=[str(op.releases['lan']), str(op.releases['protected'])])
        op.probe, op.gateway = Mock(), Mock()
        with patch.object(recovery, '_partial_http', return_value={'deployed_at': None, 'identity_source': 'raspberry_activation'}):
            with self.assertRaisesRegex(completion.CompletionFailure, 'actual handoff time'):
                op.verify_target()

    def authority_fixture(self, root):
        repo = Path(root) / 'repo'
        snapshot, context = fixture()
        context['target_source'] = completion.TARGET
        evidence = repo / 'runtime/deployments' / context['stamp']
        evidence.mkdir(parents=True)
        audit = repo / 'runtime/frontend-completions/verified-pair'
        audit.mkdir(parents=True)
        release = repo / 'runtime/frontend-releases' / (completion.TARGET + '-' + context['stamp'])
        context['release_dir'] = release
        snapshot['dashboard'].update(working_directory=str(release), process_cwd=str(release), source_sha=completion.TARGET)
        common = context['expected_contract']
        documents = {
            'summary.txt': 'Deployment failed after runtime mutation\n',
            'runtime-mutation-started': f"source={completion.TARGET}\nstarted_at={context['mutation_started_at']}\n",
            'edge-sqlite-pre-cutover.json': json.dumps({
                'schema_version': 1, 'kind': 'nexolab-edge-sqlite-pre-cutover',
                'deployed_source': context['prior_source'], 'target_source': completion.TARGET,
                'source_quick_check': 'ok', 'snapshot_quick_check': 'ok', 'outbound_queue_count': 0}),
            'frontend-artifact-import.txt': f'status=PASS\nsource_sha={completion.TARGET}\nplatform=linux/arm64\nbuild_id=build-1\n',
            'dashboard-unit-candidate.service': f'[Service]\nWorkingDirectory={release}\n' + '\n'.join(
                f'Environment={key}={value}' for key, value in {
                    'NEXT_PUBLIC_NEXOLAB_DATA_MODE': 'live', 'NEXT_PUBLIC_NEXOLAB_API_BASE_URL': common['api_base_url'],
                    'NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER': 'local',
                    'NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID': common['organization_id']}.items()) + '\n',
            'volume-identities-before.json': json.dumps(context['volumes']),
            'external-artifact-import.txt': f'status=PASS\nsource_sha={completion.TARGET}\nplatform=linux/arm64\nbuild_id=protected-build\n',
            'external-unit-candidate.service': '[Service]\nUser=nexolab\nGroup=nexolab\n' +
                f"WorkingDirectory={repo}/runtime/external-frontend-releases/{completion.TARGET}-{context['stamp']}\n" +
                f'Environment=NEXT_PUBLIC_NEXOLAB_API_BASE_URL={completion.ORIGIN}\n',
            'frontend-completion-started.json': json.dumps({
                'schema_version': 1, 'kind': 'nexolab-frontend-only-completion-started',
                'failed_attempt': context['stamp'], 'control_source': context['origin_main'],
                'target_source': completion.TARGET, 'completion_audit': str(audit), 'automatic_retry': False}),
        }
        for name, text in documents.items():
            (evidence / name).write_text(text)
        context['evidence_hashes'] = {key: recovery.sha256_file(evidence / name) for key, name in {
            'runtime_mutation_started': 'runtime-mutation-started', 'edge_sqlite_pre_cutover': 'edge-sqlite-pre-cutover.json',
            'frontend_artifact_import': 'frontend-artifact-import.txt', 'dashboard_unit_candidate': 'dashboard-unit-candidate.service',
            'volume_identities_before': 'volume-identities-before.json'}.items()}
        op = completion.Operations.__new__(completion.Operations)
        op.context, op.snapshot, op.recovery, op.failed = context, snapshot, recovery, evidence
        op.audit, op.control, op.builds = audit, context['origin_main'], {'protected': 'protected-build'}
        return repo, op

    def test_actual_publication_and_adoption_validate_paired_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            repo, op = self.authority_fixture(root)
            op.publish()
            result = json.loads((op.failed / recovery.RESULT_NAME).read_text())
            self.assertEqual(result['schema_version'], 2)
            self.assertEqual(result['safety']['runtime_mutation'], 'paired_frontends_only')
            with patch.object(adopter.forward_recovery, 'git', return_value=''), \
                    patch.object(adopter.forward_recovery, 'repository_schema_head', return_value=op.context['schema_head']):
                directory, source = adopter.authoritative_source_deployment(repo)
                self.assertEqual((directory, source), (op.failed, completion.TARGET))
                _, facts = adopter.deployment_evidence(repo, op.failed)
                self.assertEqual(facts['commit'], completion.TARGET)

    def test_paired_authority_rejects_false_safety_and_handoff_claims(self):
        with tempfile.TemporaryDirectory() as root:
            _, op = self.authority_fixture(root)
            context = recovery.frontend_completion_context(op.context, op.failed)
            result = recovery.build_frontend_completion_result(op.snapshot, context)
            for field, value in (('runtime_mutation', 'none'), ('edge_sqlite_write', 'performed'),
                                 ('postgres_write', 'performed'), ('modbus_write', 'performed')):
                bad = copy.deepcopy(result)
                bad['safety'][field] = value
                with self.assertRaises(recovery.RecoveryFailure):
                    recovery.validate_result(bad, context)
            bad = copy.deepcopy(result)
            bad['frontend_completion']['external_frontend_build_id'] = 'wrong'
            with self.assertRaises(recovery.RecoveryFailure):
                recovery.validate_result(bad, context)
            legacy = recovery.build_result(op.snapshot, op.context)
            recovery.validate_result(legacy, op.context)
            legacy['frontend_completion'] = result['frontend_completion']
            with self.assertRaises(recovery.RecoveryFailure):
                recovery.validate_result(legacy, op.context)

    def test_existing_read_only_authority_remains_valid(self):
        with tempfile.TemporaryDirectory() as root:
            repo, op = self.authority_fixture(root)
            legacy = recovery.build_result(op.snapshot, op.context)
            recovery.atomic_json(op.failed / recovery.RESULT_NAME, legacy)
            with patch.object(recovery, 'git', return_value=''), \
                    patch.object(recovery, 'repository_schema_head', return_value=op.context['schema_head']):
                self.assertEqual(recovery.load_published_authority(repo, op.failed), legacy)

    def test_adoption_rejects_changed_completion_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            repo, op = self.authority_fixture(root)
            op.publish()
            path = op.failed / 'external-unit-candidate.service'
            path.write_text(path.read_text() + '\n# changed after publication\n')
            with self.assertRaisesRegex(adopter.AdoptionFailure, 'hashes'):
                adopter.deployment_evidence(repo, op.failed)

    def test_publication_rejects_completion_marker_from_another_attempt(self):
        with tempfile.TemporaryDirectory() as root:
            _, op = self.authority_fixture(root)
            path = op.failed / 'frontend-completion-started.json'
            marker = json.loads(path.read_text())
            marker['failed_attempt'] = '20261009T155213Z'
            path.write_text(json.dumps(marker))
            with self.assertRaisesRegex(recovery.RecoveryFailure, 'marker lineage'):
                op.publish()
            self.assertFalse((op.failed / recovery.RESULT_NAME).exists())

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
