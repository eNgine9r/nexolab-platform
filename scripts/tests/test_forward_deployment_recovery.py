from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "forward_deployment_recovery.py"
SPEC = importlib.util.spec_from_file_location("forward_deployment_recovery", SCRIPT)
assert SPEC and SPEC.loader
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)

TARGET = "b" * 40
PRIOR = "a" * 40
IMAGE = "sha256:" + "c" * 64
TELEMETRY_IMAGE = "sha256:" + "d" * 64


def fixture() -> tuple[dict, dict]:
    release = Path(f"/repo/runtime/frontend-releases/{TARGET}-20260901T064156Z")
    volume = {
        "Name": "nexolab-central-postgres-data",
        "Driver": "local",
        "Mountpoint": "/var/lib/docker/volumes/nexolab-central-postgres-data/_data",
        "CreatedAt": "2026-07-24T07:43:26+03:00",
    }
    expected_contract = {
        "runtime_mode": "live",
        "api_base_url": "http://172.18.48.66:8082",
        "websocket_url": "ws://172.18.48.66:8082/api/v1/telemetry/live",
        "auth_provider": "local",
        "organization_id": "org-1",
    }
    context = {
        "stamp": "20260901T064156Z",
        "prior_source": PRIOR,
        "target_source": TARGET,
        "release_dir": release,
        "frontend": {"build_id": "build-1"},
        "expected_contract": expected_contract,
        "metadata": {"registry_revision": 20, "outbound_queue_high_water": 100},
        "schema_head": "20260828_0027",
        "origin_main": "e" * 40,
        "evidence_hashes": {"runtime_mutation_started": "1" * 64},
        "volumes": [volume],
        "mutation_started_at": "2026-09-01T09:49:45+03:00",
        "attempt_completed_at": "2026-09-01T09:50:24+03:00",
    }
    snapshot = {
        "platform": {"machine": "aarch64"},
        "dashboard": {
            "working_directory": str(release),
            "process_cwd": str(release),
            "source_sha": TARGET,
            "build_id": "build-1",
            "platform": "linux/arm64",
            "runtime_contract": expected_contract,
            "http_status": 200,
            "url": "http://172.18.48.66:3000",
        },
        "device_agent": {
            "container_id": "f" * 64,
            "created_at": "2026-09-01T06:50:13.793481+00:00",
            "image_id": IMAGE,
            "local_image_id": IMAGE,
            "docker_health": "healthy",
            "edge_volume": "nexolab-edge_edge-data",
            "status": "ok",
            "device_mode": "modbus",
            "mqtt_connected": True,
            "queue_depth": 0,
            "expected_bus_workers": 2,
            "active_bus_workers": 2,
            "workers_healthy": True,
            "registry_revision": 20,
            "latest_attempt_at": "2026-09-02T06:39:02Z",
            "sqlite": {
                "quick_check": "ok",
                "outbound_queue_count": 0,
                "outbound_queue_high_water": 101,
            },
        },
        "telemetry": {
            "container_id": "1" * 64,
            "created_at": "2026-09-01T06:49:51.327354+00:00",
            "image_id": TELEMETRY_IMAGE,
            "local_image_id": TELEMETRY_IMAGE,
            "docker_health": "healthy",
            "ready": {"status": "ready", "database": "ready", "mqtt": "ready"},
            "api": "http://172.18.48.66:8082",
            "auth_mode": "jwt",
        },
        "postgres": {
            "container_id": "2" * 64,
            "docker_health": "healthy",
            "volume_name": "nexolab-central-postgres-data",
            "schema_head": "20260828_0027",
        },
        "volumes": {volume["Name"]: copy.deepcopy(volume)},
    }
    return snapshot, context


class ForwardDeploymentRecoveryTests(unittest.TestCase):
    def assert_failure(self, snapshot: dict, context: dict, expected: str) -> None:
        with self.assertRaisesRegex(recovery.RecoveryFailure, expected):
            recovery.validate_runtime_snapshot(snapshot, context)

    def test_valid_runtime_snapshot_passes(self) -> None:
        snapshot, context = fixture()
        recovery.validate_runtime_snapshot(snapshot, context)

    def test_wrong_dashboard_source_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["dashboard"]["source_sha"] = "0" * 40
        self.assert_failure(snapshot, context, "Dashboard source")

    def test_dashboard_contract_drift_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["dashboard"]["runtime_contract"] = copy.deepcopy(
            snapshot["dashboard"]["runtime_contract"]
        )
        snapshot["dashboard"]["runtime_contract"]["auth_provider"] = "cloud"
        self.assert_failure(snapshot, context, "runtime contract")

    def test_device_agent_image_mismatch_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["device_agent"]["local_image_id"] = "sha256:" + "9" * 64
        self.assert_failure(snapshot, context, "selected local image")

    def test_device_agent_container_must_come_from_failed_attempt(self) -> None:
        snapshot, context = fixture()
        snapshot["device_agent"]["created_at"] = "2026-09-01T06:40:00+00:00"
        self.assert_failure(snapshot, context, "not created by the failed deployment")

    def test_nonempty_edge_queue_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["device_agent"]["queue_depth"] = 1
        self.assert_failure(snapshot, context, "outbound queue")

    def test_worker_mismatch_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["device_agent"]["active_bus_workers"] = 1
        self.assert_failure(snapshot, context, "bus-worker invariant")

    def test_registry_revision_drift_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["device_agent"]["registry_revision"] = 21
        self.assert_failure(snapshot, context, "registry revision")

    def test_queue_high_water_cannot_move_backward(self) -> None:
        snapshot, context = fixture()
        snapshot["device_agent"]["sqlite"]["outbound_queue_high_water"] = 99
        self.assert_failure(snapshot, context, "high-water mark moved backward")

    def test_telemetry_container_must_come_from_failed_attempt(self) -> None:
        snapshot, context = fixture()
        snapshot["telemetry"]["created_at"] = "2026-09-01T07:00:00+00:00"
        self.assert_failure(snapshot, context, "not created by the failed deployment")

    def test_telemetry_image_mismatch_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["telemetry"]["local_image_id"] = "sha256:" + "8" * 64
        self.assert_failure(snapshot, context, "Telemetry Service image")

    def test_disabled_auth_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["telemetry"]["auth_mode"] = "disabled"
        self.assert_failure(snapshot, context, "disabled/unknown")

    def test_postgres_schema_mismatch_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["postgres"]["schema_head"] = "wrong"
        self.assert_failure(snapshot, context, "PostgreSQL schema")

    def test_volume_identity_drift_fails_closed(self) -> None:
        snapshot, context = fixture()
        snapshot["volumes"]["nexolab-central-postgres-data"]["CreatedAt"] = "later"
        self.assert_failure(snapshot, context, "volume identities changed")

    def test_result_hash_forgery_fails_closed(self) -> None:
        snapshot, context = fixture()
        result = recovery.build_result(snapshot, context)
        result["evidence_hashes"] = {"runtime_mutation_started": "0" * 64}
        with self.assertRaisesRegex(recovery.RecoveryFailure, "hashes"):
            recovery.validate_result(result, context)

    def test_result_safety_forgery_fails_closed(self) -> None:
        snapshot, context = fixture()
        result = recovery.build_result(snapshot, context)
        result["safety"]["edge_sqlite_write"] = "performed"
        with self.assertRaisesRegex(recovery.RecoveryFailure, "safety"):
            recovery.validate_result(result, context)

    def test_later_mutating_attempt_always_blocks_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            root = repo / "runtime" / "deployments"
            later = root / "20260902T000000Z"
            later.mkdir(parents=True)
            (later / "runtime-mutation-started").write_text("source=x\n", encoding="utf-8")
            (later / recovery.RESULT_NAME).write_text(
                json.dumps({"status": "reconciled"}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                recovery.RecoveryFailure,
                "latest runtime mutation attempt",
            ):
                recovery.ensure_no_newer_mutation(repo, "20260901T064156Z")


class PartialActivationContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.failed = self.repo / 'runtime/deployments/20261009T155213Z'
        self.failed.mkdir(parents=True)
        self.capture_path = self.repo / 'capture.json'
        self.recovery_path = self.repo / 'recovery.json'
        self.agent_id = '1' * 64
        self.volume = {'Name': 'nexolab-edge_edge-data', 'Driver': 'local', 'Mountpoint': '/edge', 'CreatedAt': 'before'}
        self.agent = {'id': self.agent_id, 'image_id': IMAGE, 'project': 'nexolab-edge',
                      'service': 'device-agent', 'running': True, 'docker_health': 'healthy'}
        self.snapshot = {'kind': 'nexolab-edge-sqlite-pre-cutover', 'schema_version': 1,
            'deployment_evidence_id': self.failed.name, 'deployed_source': PRIOR, 'target_source': TARGET,
            'deployed_device_agent_image_id': IMAGE, 'source_quick_check': 'ok', 'snapshot_quick_check': 'ok'}
        self.recovery = {'status': 'agent_recovery_verified', 'runtime_mutation': 'device_agent_only',
            'database_restore': 'none', 'package_authority': 'not_modified',
            'recovery_image_id': IMAGE, 'recovered_container_id': self.agent_id,
            'persistent_volume_identity': 'all_existing_unchanged', 'non_agent_containers': 'unchanged'}
        self.write(self.failed / 'edge-sqlite-pre-cutover.json', self.snapshot)
        self.write(self.failed / 'edge-device-agent-quiesce.json', {'kind': 'nexolab-edge-device-agent-quiesce',
            'schema_version':1, 'deployment_evidence_id': self.failed.name, 'target_source': TARGET, 'image_id': IMAGE})
        (self.failed / 'runtime-mutation-started').write_text(f'source={TARGET}\nstarted_at=2026-10-09T16:04:34Z\n')
        (self.failed / 'summary.txt').write_text('failed after mutation\n')
        self.write(self.recovery_path, self.recovery)
        (self.repo/'infrastructure/compose').mkdir(parents=True)
        for name in ('.env.central','.env.edge-central'):
            (self.repo/'infrastructure/compose'/name).write_text('SITE_VALUE=preserved\n')
        self.write(self.failed/'volume-identities-before.json',[self.volume])
        self.facts = {'containers': [self.agent], 'all_existing_volumes': [self.volume],
            'agent_exact_recovered_image': True,
            'snapshot_metadata': {'metadata_sha256': recovery.sha256_file(self.failed / 'edge-sqlite-pre-cutover.json')},
            'attempt_quiesce': {'metadata_sha256': recovery.sha256_file(self.failed / 'edge-device-agent-quiesce.json')},
            'attempt_mutation_marker': {'metadata_sha256': recovery.sha256_file(self.failed / 'runtime-mutation-started')},
            'prior_recovery': {'metadata_sha256': recovery.sha256_file(self.recovery_path)},
            'frontends': {profile: {'http_status': 200, 'active_port': port, 'port_contract_verified': True,
                'identity': {'schema_version': 'nexolab-runtime-identity-v1', 'service': 'dashboard',
                             'source_commit': source, 'build_id': profile},
                'unit': {'WorkingDirectory': '/'+profile}, 'process_cwd': '/'+profile}
                for profile, port, source in [('lan',3000,PRIOR), ('protected',3100,'f'*40)]},
            'central_ready': {'endpoint': ['172.18.48.66',8082], 'http_status': 200,
                              'status': 'ready', 'database': 'ready', 'mqtt': 'ready'}}
        self.facts['agent_health']=[{'status':'ok','mqtt_connected':True,'workers_healthy':True,
            'expected_bus_workers':3,'active_bus_workers':3,'samples_total':value} for value in (10,11)]
        self.facts['existing_volume_count']=1
        self.write_capture()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, value):
        path.write_text(json.dumps(value)+'\n')

    def write_capture(self):
        self.write(self.capture_path, {'kind':'nexolab-unified-runtime-check-1323', 'capture_version':2,
            'status':'captured', 'runtime_mutation':'none', 'facts':self.facts})

    def validate(self):
        with patch.object(recovery, 'check_partial_live_baseline') as live:
            result = recovery.validate_partial_continuation(self.repo, self.failed, PRIOR, TARGET,
                self.capture_path, recovery.sha256_file(self.capture_path), self.recovery_path)
        live.assert_called_once()
        return result

    def test_partial_plan_is_not_success_or_source_authority(self):
        result = self.validate()
        self.assertEqual(result['status'],'validated_partial_baseline')
        self.assertEqual(result['baseline_scope'],'partial_only_not_deployment_authority')
        self.assertEqual(result['recovered_device_agent_image_id'],IMAGE)
        self.assertFalse((self.failed / recovery.RESULT_NAME).exists())
        self.assertFalse((self.failed / 'final-state.txt').exists())

    def test_wrong_target_cannot_skip_unresolved_mutation(self):
        self.snapshot['target_source']='e'*40
        self.write(self.failed/'edge-sqlite-pre-cutover.json',self.snapshot)
        with self.assertRaises(recovery.RecoveryFailure):self.validate()

    def test_restore_or_fake_recovery_rejected(self):
        for key, value in [('database_restore','restored'),('status','recovered'),('recovery_image_id','sha256:'+'9'*64)]:
            with self.subTest(key=key):
                changed={**self.recovery,key:value};self.write(self.recovery_path,changed)
                with self.assertRaises(recovery.RecoveryFailure):self.validate()
        self.write(self.recovery_path,self.recovery)

    def test_completed_attempt_cannot_be_reused_as_partial(self):
        (self.failed/'final-state.txt').write_text('commit='+TARGET+'\n')
        with self.assertRaises(recovery.RecoveryFailure):self.validate()

    def test_original_metadata_drift_fails_closed(self):
        (self.failed/'runtime-mutation-started').write_text(f'source={TARGET}\nstarted_at=changed\n')
        with self.assertRaises(recovery.RecoveryFailure):self.validate()

    def test_old_or_defective_capture_cannot_authorize_continuation(self):
        document=json.loads(self.capture_path.read_text());document['capture_version']=1
        self.write(self.capture_path,document)
        with self.assertRaises(recovery.RecoveryFailure):self.validate()

    def test_capture_digest_is_mandatory(self):
        with self.assertRaises(recovery.RecoveryFailure):
            recovery.validate_partial_continuation(self.repo,self.failed,PRIOR,TARGET,self.capture_path,'0'*64,self.recovery_path)

    def test_volume_inventory_must_be_unique_and_nonempty(self):
        for volumes in ([], [self.volume,self.volume]):
            self.facts['all_existing_volumes']=volumes;self.write_capture()
            with self.assertRaises(recovery.RecoveryFailure):self.validate()

    def test_live_drift_cannot_be_ignored(self):
        with patch.object(recovery,'check_partial_live_baseline',side_effect=recovery.RecoveryFailure('runtime drift')):
            with self.assertRaisesRegex(recovery.RecoveryFailure,'runtime drift'):
                recovery.validate_partial_continuation(self.repo,self.failed,PRIOR,TARGET,self.capture_path,
                    recovery.sha256_file(self.capture_path),self.recovery_path)

    def test_all_volume_identity_check_allows_new_volumes_but_rejects_replacement(self):
        with patch.object(recovery,'_partial_run',return_value=json.dumps([self.volume])):
            recovery.check_partial_volume_preservation(self.facts)
        with patch.object(recovery,'_partial_run',return_value=json.dumps([{**self.volume,'CreatedAt':'recreated'}])):
            with self.assertRaises(recovery.RecoveryFailure):recovery.check_partial_volume_preservation(self.facts)

    def test_readonly_command_failure_does_not_leak_credentials(self):
        import subprocess
        with patch.object(recovery.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'SECRET','SECRET')):
            with self.assertRaises(recovery.RecoveryFailure) as error:recovery._partial_run('docker','inspect','1'*64)
        self.assertNotIn('SECRET',str(error.exception))

    def live_fixture(self):
        def container(identifier, image, project, service):
            return {'Id':identifier,'Image':image,'Name':'/'+service,
                'Config':{'User':'nonroot','WorkingDir':'/app','Env':['PASSWORD=SECRET'],
                    'Labels':{'com.docker.compose.project':project,'com.docker.compose.service':service}},
                'State':{'Running':True,'Status':'running','OOMKilled':False,'Health':{'Status':'healthy','Log':[{'Output':'SECRET'}]}},
                'Mounts':[], 'HostConfig':{'PortBindings':{'8082/tcp':[{'HostIp':'172.18.48.66','HostPort':'8082'}]}}}
        docs={self.agent_id:container(self.agent_id,IMAGE,'nexolab-edge','device-agent'),
              '2'*64:container('2'*64,TELEMETRY_IMAGE,'nexolab-central','telemetry-service')}
        self.facts['containers']=[{'id':d['Id'],'image_id':d['Image'],'name':d['Name'],
            'project':d['Config']['Labels']['com.docker.compose.project'],
            'service':d['Config']['Labels']['com.docker.compose.service'],
            'user':'nonroot','working_dir':'/app','running':True,'status':'running','oom_killed':False,
            'docker_health':'healthy','named_volumes':[]} for d in docs.values()]
        calls=[]
        def run(*args):
            calls.append(args)
            if args[:3]==('docker','ps','-aq'):
                return self.agent_id if args[-1].endswith('nexolab-edge') else '2'*64
            if args[:2]==('docker','inspect'):return json.dumps([docs[args[-1]]])
            if args[:3]==('docker','volume','inspect'):return json.dumps([self.volume])
            if args[:3]==('docker','volume','ls'):return self.volume['Name']
            if args[:2]==('systemctl','show'):
                profile='lan' if args[2]=='nexolab-dashboard.service' else 'protected'
                port=3000 if profile=='lan' else 3100
                pid=123 if profile=='lan' else 124
                return f'WorkingDirectory=/{profile}\nMainPID={pid}\nActiveState=active\nExecStart=next start --port {port} SECRET'
            if args[0]=='ip':return json.dumps([{'addr_info':[{'family':'inet','local':'172.18.48.66'}]}])
            raise AssertionError('unadvertised operation')
        samples=iter((10,11))
        def http(host,port,route):
            if port in (3000,3100):return self.facts['frontends']['lan' if port==3000 else 'protected']['identity']
            if port==8082:return {'status':'ready','database':'ready','mqtt':'ready'}
            if port==8081:return {'status':'ok','mqtt_connected':True,'queue_depth':0,'samples_total':next(samples),
                'acquisition':{'scheduler':{'workers_healthy':True,'expected_bus_workers':3,'active_bus_workers':3}}}
            raise AssertionError('unexpected destination')
        return docs,run,http,calls

    def test_live_baseline_checks_distinct_profiles_workers_api_and_all_volumes_readonly(self):
        docs,run,http,calls=self.live_fixture()
        with patch.object(recovery,'_partial_run',side_effect=run),patch.object(recovery,'_partial_http',side_effect=http),\
            patch.object(recovery.platform,'machine',return_value='aarch64'),patch.object(recovery.os,'readlink',side_effect=lambda p:'/lan' if '/123/' in p else '/protected'),patch.object(recovery.time,'sleep'):
            recovery.check_partial_live_baseline(self.facts)
        for call in calls:
            self.assertNotIn('SECRET',str(call))
            if call[0]=='docker':self.assertIn(call[1],('ps','inspect','volume'))

    def test_changed_image_stops_before_any_http_probe(self):
        docs,run,http,calls=self.live_fixture();docs[self.agent_id]['Image']='sha256:'+'9'*64
        with patch.object(recovery,'_partial_run',side_effect=run),patch.object(recovery,'_partial_http') as probe,patch.object(recovery.platform,'machine',return_value='aarch64'):
            with self.assertRaisesRegex(recovery.RecoveryFailure,'baseline drifted'):recovery.check_partial_live_baseline(self.facts)
        probe.assert_not_called()

    def test_rebound_api_never_probes_remote_host(self):
        docs,run,http,calls=self.live_fixture();docs['2'*64]['HostConfig']['PortBindings']['8082/tcp'][0]['HostIp']='8.8.8.8'
        with patch.object(recovery,'_partial_run',side_effect=run),patch.object(recovery,'_partial_http',side_effect=http) as probe,\
            patch.object(recovery.platform,'machine',return_value='aarch64'),patch.object(recovery.os,'readlink',side_effect=lambda p:'/lan' if '/123/' in p else '/protected'):
            with self.assertRaisesRegex(recovery.RecoveryFailure,'socket baseline drifted'):recovery.check_partial_live_baseline(self.facts)
        self.assertTrue(all(c.args[0]=='127.0.0.1' for c in probe.call_args_list))

    def test_flat_acquisition_cannot_validate_recovered_agent(self):
        docs,run,http,calls=self.live_fixture()
        def fetch(host,port,route):
            if port==8081:return {'status':'ok','mqtt_connected':True,'queue_depth':0,'samples_total':10,
                'acquisition':{'scheduler':{'workers_healthy':True,'expected_bus_workers':3,'active_bus_workers':3}}}
            return http(host,port,route)
        with patch.object(recovery,'_partial_run',side_effect=run),patch.object(recovery,'_partial_http',side_effect=fetch),\
            patch.object(recovery.platform,'machine',return_value='aarch64'),patch.object(recovery.os,'readlink',side_effect=lambda p:'/lan' if '/123/' in p else '/protected'),\
            patch.object(recovery.time,'sleep'),patch.object(recovery.time,'monotonic',side_effect=(0,0,16)):
            with self.assertRaisesRegex(recovery.RecoveryFailure,'not advancing'):recovery.check_partial_live_baseline(self.facts)

    def test_site_setting_drift_prevents_success_publication(self):
        context=self.validate()
        recovery.check_partial_input_preservation(self.repo,self.failed,self.recovery_path,context)
        (self.repo/'infrastructure/compose/.env.central').write_text('SECRET=new-value\n')
        with self.assertRaisesRegex(recovery.RecoveryFailure,'configuration changed'):
            recovery.check_partial_input_preservation(self.repo,self.failed,self.recovery_path,context)

    def test_original_evidence_drift_prevents_success_publication(self):
        context=self.validate()
        (self.failed/'runtime-mutation-started').write_text('source=changed\n')
        with self.assertRaisesRegex(recovery.RecoveryFailure,'original evidence changed'):
            recovery.check_partial_input_preservation(self.repo,self.failed,self.recovery_path,context)

    def test_canonical_docker_volume_metadata_uses_only_identity_fields(self):
        self.write(self.failed/'volume-identities-before.json', [{**self.volume,'Scope':'local','Options':None,'Labels':{'extra':'not-an-identity'}}])
        self.assertEqual(self.validate()['status'],'validated_partial_baseline')


if __name__ == "__main__":
    unittest.main()
