from __future__ import annotations

import copy
from contextlib import redirect_stdout
import importlib.util
import io
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
            op.context, op.control = {'stamp': completion.ATTEMPT}, '0' * 40
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
                activation = json.loads((op.audit / 'frontend-activation.json').read_text())
                self.assertEqual(activation['frontend_activated_at'], op.frontend_activated_at)
                self.assertEqual(activation['identity_manifest_sha256'], recovery.sha256_file(op.identity_path))
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

    def authority_fixture(self, root, *, stamp=None, control=None, audit_name='verified-pair', activated_at=None):
        repo = Path(root) / 'repo'
        snapshot, context = fixture()
        context['target_source'] = completion.TARGET
        if stamp:
            context['stamp'] = stamp
        if control:
            context['origin_main'] = control
        evidence = repo / 'runtime/deployments' / context['stamp']
        evidence.mkdir(parents=True)
        audit = repo / 'runtime/frontend-completions' / audit_name
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
        frontend_activated_at = activated_at or completion.datetime.now(completion.timezone.utc).isoformat()
        manifest = repo / 'runtime' / ('frontend-completion-identity-' + audit.name + '.json')
        manifest.write_text(json.dumps({
            'schema_version': 'nexolab-runtime-identity-v1', 'service': 'dashboard',
            'source_commit': completion.TARGET, 'build_id': 'build-1',
            'identity_source': 'raspberry_activation', 'deployed_at': frontend_activated_at}))
        (audit / 'frontend-activation.json').write_text(json.dumps({
            'schema_version': 1, 'kind': 'nexolab-frontend-completion-activation',
            'failed_attempt': context['stamp'], 'target_source': completion.TARGET,
            'control_source': context['origin_main'], 'frontend_activated_at': frontend_activated_at,
            'identity_manifest': str(manifest), 'identity_manifest_sha256': recovery.sha256_file(manifest)}))
        context['evidence_hashes'] = {key: recovery.sha256_file(evidence / name) for key, name in {
            'runtime_mutation_started': 'runtime-mutation-started', 'edge_sqlite_pre_cutover': 'edge-sqlite-pre-cutover.json',
            'frontend_artifact_import': 'frontend-artifact-import.txt', 'dashboard_unit_candidate': 'dashboard-unit-candidate.service',
            'volume_identities_before': 'volume-identities-before.json'}.items()}
        op = completion.Operations.__new__(completion.Operations)
        op.context, op.snapshot, op.recovery, op.failed = context, snapshot, recovery, evidence
        op.audit, op.control, op.builds = audit, context['origin_main'], {'protected': 'protected-build'}
        op.frontend_activated_at = frontend_activated_at
        op.predecessor = None
        return repo, op

    def continuation_fixture(self, root):
        repo, op = self.authority_fixture(root, stamp=completion.ATTEMPT,
            control=recovery.CONTRACT_FAILURE_CONTROL, audit_name=recovery.CONTRACT_FAILURE_AUDIT,
            activated_at='2026-10-10T21:45:58.900316+00:00')
        report = {'kind': 'nexolab-paired-frontend-completion', 'schema_version': 1,
            'status': 'stopped_unverified', 'automatic_retry': False,
            'failed_attempt': completion.ATTEMPT, 'control_source': recovery.CONTRACT_FAILURE_CONTROL,
            'started_at': '2026-10-10T21:44:39.365999+00:00', 'execute': True,
            'failed_stage': 'paired_handoff_and_genuine_reconciliation', 'error_type': 'RecoveryFailure',
            'reason': 'active Dashboard runtime contract does not match failed evidence',
            'failure_location': {'file': 'scripts/forward_deployment_recovery.py',
                                 'function': 'validate_runtime_snapshot', 'line': 684},
            'finished_at': '2026-10-10T21:46:34.797614+00:00'}
        (op.audit / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        for profile in ('lan', 'protected'):
            (op.audit / (profile + '-unit-before.service')).write_text('original ' + profile + ' unit\n')
        self.assertEqual(recovery.sha256_file(op.audit / 'report.json'), recovery.CONTRACT_FAILURE_REPORT_SHA)
        previous = recovery.completion_contract_predecessor(op.context, op.failed)
        op.predecessor = previous
        op.audit = repo / 'runtime/frontend-completions/next-reviewed-pair'
        op.audit.mkdir()
        op.control = op.context['origin_main'] = 'f' * 40
        op.builds['lan'] = 'build-1'
        op.identity_path = repo / 'runtime' / ('frontend-completion-identity-' + op.audit.name + '.json')
        op.owner = SimpleNamespace(pw_uid=0, pw_gid=0)
        with patch.object(completion.os, 'chown'):
            op.write_identity(completion.datetime.now(completion.timezone.utc).isoformat())
        return repo, op

    def test_continuation_preserves_original_marker_and_authority_binds_both_audits(self):
        with tempfile.TemporaryDirectory() as root:
            repo, op = self.continuation_fixture(root)
            original = op.failed / 'frontend-completion-started.json'
            before = original.read_bytes()
            op.mark_started()
            self.assertEqual(original.read_bytes(), before)
            with self.assertRaisesRegex(completion.CompletionFailure, 'no retry'):
                op.mark_started()
            op.publish()
            result = json.loads((op.failed / recovery.RESULT_NAME).read_text())
            self.assertEqual(result['frontend_completion']['predecessor_audit'], op.predecessor['frontend_completion']['audit'])
            self.assertIn('frontend_completion_previous_report', result['evidence_hashes'])
            self.assertIn('frontend_completion_continuation_started', result['evidence_hashes'])
            with patch.object(adopter.forward_recovery, 'git', return_value=''), \
                    patch.object(adopter.forward_recovery, 'repository_schema_head', return_value=op.context['schema_head']):
                _, facts = adopter.deployment_evidence(repo, op.failed)
                self.assertEqual(facts['deployed_at'], op.frontend_activated_at)
                report_path = Path(op.predecessor['frontend_completion']['audit']) / 'report.json'
                report_path.write_text(report_path.read_text() + ' ')
                with self.assertRaisesRegex(adopter.AdoptionFailure, 'predecessor'):
                    adopter.deployment_evidence(repo, op.failed)

    def test_continuation_rejects_changed_predecessor_and_same_activation_audit(self):
        for change in ('report', 'marker', 'activation', 'continuation'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as root:
                _, op = self.continuation_fixture(root)
                op.mark_started()
                prior = Path(op.predecessor['frontend_completion']['audit'])
                if change == 'report':
                    path = prior / 'report.json'; path.write_text(path.read_text() + ' ')
                else:
                    path = (op.failed / 'frontend-completion-started.json' if change == 'marker'
                            else prior / 'frontend-activation.json' if change == 'activation'
                            else op.failed / recovery.CONTRACT_CONTINUATION_MARKER)
                    data = json.loads(path.read_text())
                    key = 'target_source' if change == 'marker' else 'frontend_activated_at' if change == 'activation' else 'completion_audit'
                    data[key] = '0' * 40 if change == 'marker' else '2026-10-10T23:00:00+00:00' if change == 'activation' else str(prior)
                    path.write_text(json.dumps(data))
                with self.assertRaises(recovery.RecoveryFailure):
                    op.publish()
                self.assertFalse((op.failed / recovery.RESULT_NAME).exists())

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
                self.assertEqual(facts['deployed_at'], op.frontend_activated_at)
                self.assertNotEqual(facts['deployed_at'], op.context['mutation_started_at'])

    def test_check_only_revalidates_published_v2_without_writing(self):
        with tempfile.TemporaryDirectory() as root:
            repo, op = self.authority_fixture(root)
            op.publish()
            context = {**op.context, 'evidence': op.failed}
            before = {p: p.read_bytes() for p in repo.rglob('*') if p.is_file()}
            with patch.object(recovery, 'build_context', return_value=context), \
                    patch.object(recovery, 'collect_runtime_snapshot', return_value=op.snapshot), \
                    patch.object(recovery, 'git', return_value=''), \
                    patch.object(recovery, 'repository_schema_head', return_value=context['schema_head']), \
                    redirect_stdout(io.StringIO()):
                code = recovery.main(['--repo', str(repo), '--deployment-evidence', str(op.failed),
                                      '--expected-prior-source', context['prior_source'],
                                      '--expected-target-source', completion.TARGET, '--check-only'])
            self.assertEqual(code, 0)
            self.assertEqual(before, {p: p.read_bytes() for p in repo.rglob('*') if p.is_file()})

    def test_paired_activation_timestamp_cannot_reuse_backend_time(self):
        with tempfile.TemporaryDirectory() as root:
            _, op = self.authority_fixture(root)
            context = recovery.frontend_completion_context(op.context, op.failed)
            result = recovery.build_frontend_completion_result(op.snapshot, context)
            result['runtime_activated_at'] = op.context['mutation_started_at']
            with self.assertRaises(recovery.RecoveryFailure):
                recovery.validate_result(result, context)

    def test_changed_activation_manifest_blocks_adoption(self):
        with tempfile.TemporaryDirectory() as root:
            repo, op = self.authority_fixture(root)
            op.publish()
            path = repo / 'runtime' / ('frontend-completion-identity-' + op.audit.name + '.json')
            identity = json.loads(path.read_text())
            identity['deployed_at'] = op.context['mutation_started_at']
            path.write_text(json.dumps(identity))
            with self.assertRaises(adopter.AdoptionFailure):
                adopter.deployment_evidence(repo, op.failed)

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
