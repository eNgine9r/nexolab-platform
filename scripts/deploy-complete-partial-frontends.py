#!/usr/bin/env python3
"""Owner-local paired frontend completion of the exact latest failed attempt.

Existing healthy backend and newer acquisition remain in place. No retries.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import platform
import pwd
import re
import signal
import subprocess
import tempfile

REPO = Path('/home/nexolab/nexolab-platform')
STAGE = Path('/home/nexolab/commander-workspaces/nexolab-platform/guarded-update-1313-df5485f6')
ATTEMPT = '20261010T194054Z'
TARGET = 'c296c58f3cb2b221b88a8d4e9d6a4cf67e5e33e2'
PREVIOUS = 'd00a83bfc83fb120777c721b5e46fa50ae455c7d'
ORIGIN = 'https://nexolab-edge-01.tail7f9b04.ts.net'
EXPECTED_METADATA = {
    'kind': 'nexolab-edge-sqlite-pre-cutover', 'schema_version': 1,
    'deployment_evidence_id': ATTEMPT, 'deployed_source': PREVIOUS, 'target_source': TARGET,
    'sha256': 'f64b524d11da19bbea7a8530bb3de790cee38c1d47886e234a13bf1790e73a15',
    'bytes': 290816, 'registry_revision': 22, 'outbound_queue_count': 0,
    'outbound_queue_high_water': 10948434, 'source_quick_check': 'ok', 'snapshot_quick_check': 'ok',
    'deployed_device_agent_image_id': 'sha256:514b504bad13e8cf4d7776a4e0670fb187d8149aa8ca75d6abc6b814ad2da323',
}
EXPECTED_QUIESCE = {
    'kind': 'nexolab-edge-device-agent-quiesce', 'schema_version': 1,
    'deployment_evidence_id': ATTEMPT, 'target_source': TARGET,
    'container_id': '614e5d1e26f96eba43810662f24e3fdac65f7921c069295186054713749ff428',
    'image_id': EXPECTED_METADATA['deployed_device_agent_image_id'],
}
EXPECTED_COMPONENTS = {
    'device_agent': ('2b1b802e40605dd248ea22ab47b2ab5777e780513c0a2dd6d52581e87909bac3',
                     'sha256:3d50e14ceb396ab9e442f26b66703838a86e7b7d6e5b79373ef62f45bee94037'),
    'telemetry': ('41d62f0bac281ef89e98123230a4a5bdeeaf7b20f0a9759211484f569cbb8da7',
                  'sha256:20980e18e6f48e05304e28a0810932102804b3e402d45188bf11c473fe4d9a19'),
}
OLD_IDENTITIES = {
    'lan': (PREVIOUS, 'hA8usmV6ZKwgZUYhmOLHZ'),
    'protected': ('4b9dc85ab2e7924195d5d2030fb298aaaf78aaf4', 'KVMryq76dj1LhzOW30pgA'),
}
OLD_RELEASES = {
    'lan': REPO / 'runtime/frontend-releases/d00a83bfc83fb120777c721b5e46fa50ae455c7d-20261008T092219Z',
    'protected': Path('/home/nexolab/commander-workspaces/nexolab-external-stage/source-4b9dc85'),
}
UNITS = {'lan': 'nexolab-dashboard.service', 'protected': 'nexolab-external-frontend.service'}
PORTS = {'lan': 3000, 'protected': 3100}
EXPECTED_BUS_WORKERS = 3  # Fresh actual site observation; no old recovery report.


class CompletionFailure(RuntimeError):
    pass


def validate_latest_lineage(metadata, quiesce):
    if (any(metadata.get(k) != v for k, v in EXPECTED_METADATA.items())
            or any(quiesce.get(k) != v for k, v in EXPECTED_QUIESCE.items())):
        raise CompletionFailure('latest private attempt lineage differs from owner evidence')


def require_unchanged(before, after):
    if before != after:
        raise CompletionFailure('frontend completion changed persistent volumes or runtime containers')


def handoff(operations):
    touched = []
    publishing = False
    try:
        operations.mark_started()
        for profile in ('lan', 'protected'):
            touched.append(profile)  # Stop/start errors still require recovery.
            operations.activate(profile)
        operations.verify_target()
        publishing = True
        operations.publish()
    except BaseException:
        if publishing and operations.publication_exists():
            raise CompletionFailure('authority publication uncertain; preserve verified target pair and audit') from None
        failures = []
        for profile in reversed(touched):
            try:
                operations.restore(profile)
            except BaseException:
                failures.append(profile)
        try:
            operations.verify_restored()
        except BaseException:
            failures.append('pair_or_gateway')
        if failures:
            raise CompletionFailure('frontend rollback unverified; preserve audit and stop') from None
        operations.restoration = 'original_frontend_pair_and_gateway_verified'
        raise


def load_helper(name, filename):
    spec = importlib.util.spec_from_file_location(name, REPO / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Operations:
    def __init__(self, control, audit, owner, launcher, recovery, gateway, continue_contract_failure=False):
        self.control, self.audit, self.owner = control, audit, owner
        self.launcher, self.recovery, self.gateway = launcher, recovery, gateway
        self.failed = REPO / 'runtime/deployments' / ATTEMPT
        self.context = recovery.build_context(REPO, self.failed, PREVIOUS, TARGET)
        self.continue_contract_failure = continue_contract_failure
        validate_latest_lineage(self.context['metadata'], recovery.read_json(
            self.failed / 'edge-device-agent-quiesce.json', 'latest quiesce'))
        snapshot = self.failed / 'edge-sqlite-pre-cutover.db'
        recovery._safe_file(snapshot, 'latest SQLite snapshot')
        if snapshot.stat().st_size != EXPECTED_METADATA['bytes'] or launcher.digest(snapshot) != EXPECTED_METADATA['sha256']:
            raise CompletionFailure('latest preserved SQLite snapshot digest differs')
        for filename in ('final-state.txt', 'edge-sqlite-restore-result.json', recovery.RESULT_NAME,
                         recovery.CONTRACT_CONTINUATION_MARKER):
            if (self.failed / filename).exists() or (self.failed / filename).is_symlink():
                raise CompletionFailure('latest attempt already completed, restored or completion attempted')
        self.predecessor = None
        original_marker = self.failed / 'frontend-completion-started.json'
        if continue_contract_failure:
            self.predecessor = recovery.completion_contract_predecessor(self.context, self.failed)
        elif original_marker.exists() or original_marker.is_symlink():
            raise CompletionFailure('completion already attempted; explicit reviewed contract continuation required')
        self.identity_path = REPO / 'runtime' / ('frontend-completion-identity-' + audit.name + '.json')
        self.candidate_identity_path = self.identity_path.with_name(self.identity_path.stem + '-candidate.json')
        self.node = Path('/home/nexolab/.nvm/versions/node') / ('v' + (REPO / '.nvmrc').read_text().strip()) / 'bin/node'
        self.releases, self.builds, self.old_units, self.new_units = {}, {}, {}, {}
        self.live_high_water = None
        self.input_hashes = {p: launcher.digest(p) for p in (
            self.failed / 'edge-device-agent-quiesce.json', self.failed / 'edge-sqlite-pre-cutover.json',
            self.failed / 'runtime-mutation-started', self.failed / 'summary.txt',
            self.failed / 'frontend-artifact-import.txt', self.failed / 'external-artifact-import.txt',
            self.failed / 'volume-identities-before.json',
            self.failed / 'dashboard-unit-candidate.service', self.failed / 'external-unit-candidate.service',
            REPO / '.env.local', REPO / 'infrastructure/compose/.env.central',
            REPO / 'infrastructure/compose/.env.edge-central', Path('/opt/nexolab-external/nginx.conf'),
            Path('/etc/systemd/system/nexolab-external-nginx.service'),
            Path('/etc/systemd/system/nexolab-google-oauth-stage.service'))}
        if self.predecessor:
            predecessor_audit = Path(self.predecessor['frontend_completion']['audit'])
            for path in (original_marker, predecessor_audit / 'report.json',
                         predecessor_audit / 'frontend-activation.json',
                         REPO / 'runtime' / ('frontend-completion-identity-' + predecessor_audit.name + '.json')):
                self.input_hashes[path] = launcher.digest(path)
        self.before = self.footprint()
        historical = recovery.read_json(launcher.CAPTURE, 'historical volume identity reference')
        if launcher.digest(launcher.CAPTURE) != launcher.CAPTURE_SHA:
            raise CompletionFailure('historical volume identity reference changed')
        existing = {v['Name']: v for v in self.before['volumes']}
        for item in historical['facts']['all_existing_volumes']:
            if existing.get(item['Name']) != item:
                raise CompletionFailure('original persistent volume identity differs')
        self.check_data()
        self.verify_restored()
        gateway.require_gateway_active(gateway.origin_host(ORIGIN))
        for profile in ('lan', 'protected'):
            artifact = launcher.verify_artifact(profile)
            filename = 'dashboard-unit-candidate.service' if profile == 'lan' else 'external-unit-candidate.service'
            unit = (self.failed / filename).read_text()
            values = gateway.directives(unit)
            release = REPO / 'runtime' / ('frontend-releases' if profile == 'lan' else 'external-frontend-releases') / (TARGET + '-' + ATTEMPT)
            if values.get('WorkingDirectory') != str(release) or values.get('User') != 'nexolab' or values.get('Group') != 'nexolab':
                raise CompletionFailure('latest candidate path or frontend account differs')
            if release.is_symlink() or not release.is_dir() or release.resolve() != release:
                raise CompletionFailure('latest candidate release path unsafe')
            self.run('/usr/bin/sha256sum', '--check', '--status', str(artifact / 'frontend-runtime-files-sha256.txt'), cwd=release, timeout=180)
            self.builds[profile] = launcher.ARTIFACTS[profile]['build_id']
            if (release / '.next/BUILD_ID').read_text().strip() != self.builds[profile]:
                raise CompletionFailure('candidate build differs from verified artifact')
            self.releases[profile] = release
            for name in ('frontend-source-sha.txt', 'frontend-platform.txt', 'frontend-runtime-contract.txt'):
                if (release / name).read_bytes() != (artifact / name).read_bytes():
                    raise CompletionFailure('candidate source or runtime contract differs from artifact')
            if profile == 'lan':
                recovery.validate_lan_runtime_contract(recovery.parse_key_values(
                    release / 'frontend-runtime-contract.txt', 'candidate LAN contract'),
                    self.context['expected_contract'])
            self.old_units[profile] = Path('/etc/systemd/system', UNITS[profile]).read_text()
            if self.predecessor:
                predecessor_unit = predecessor_audit / (profile + '-unit-before.service')
                recovery._safe_file(predecessor_unit, 'previous frontend unit')
                if predecessor_unit.read_text() != self.old_units[profile]:
                    raise CompletionFailure('previous frontend unit was not restored exactly')
                self.input_hashes[predecessor_unit] = launcher.digest(predecessor_unit)
            (audit / (profile + '-unit-before.service')).write_text(self.old_units[profile])
            if profile == 'lan':
                key = 'Environment=NEXOLAB_RUNTIME_IDENTITY_FILE='
                rows = unit.splitlines()
                if sum(row.startswith(key) for row in rows) != 1:
                    raise CompletionFailure('LAN candidate identity directive ambiguous')
                unit = '\n'.join(key + str(self.identity_path) if row.startswith(key) else row for row in rows) + '\n'
            else:
                gateway.validate(unit, Path('/opt/nexolab-external/nginx.conf').read_text(), ORIGIN,
                                 self.context['expected_contract']['organization_id'])
            self.new_units[profile] = unit
            (audit / (profile + '-unit-candidate.service')).write_text(unit)

    def run(self, *args, cwd=None, timeout=30):
        # Privileged host tools never resolve through the service owner's Node PATH.
        command = ['/usr/bin/' + args[0], *args[1:]] if '/' not in args[0] else list(args)
        return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True,
                              timeout=timeout, env=self.launcher.environment(self.node.parent)).stdout.strip()

    def footprint(self):
        containers = []
        for project in ('nexolab-central', 'nexolab-edge'):
            ids = self.run('docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project).split()
            for document in json.loads(self.run('docker', 'inspect', *ids)):
                containers.append(self.recovery._partial_container_baseline(self.recovery._partial_container(document)))
        names = self.run('docker', 'volume', 'ls', '-q').split()
        volumes = [{k: v.get(k) for k in ('Name', 'Driver', 'Mountpoint', 'CreatedAt')}
                   for v in json.loads(self.run('docker', 'volume', 'inspect', *names))]
        return {'containers': sorted(containers, key=lambda v: v['id']), 'volumes': sorted(volumes, key=lambda v: v['Name'])}

    def check_data(self):
        snapshot = self.recovery.collect_runtime_snapshot(self.context)
        self.recovery.validate_runtime_data_snapshot(snapshot, self.context)
        high_water = snapshot['device_agent']['sqlite']['outbound_queue_high_water']
        if self.live_high_water is not None and high_water < self.live_high_water:
            raise CompletionFailure('live SQLite high-water regressed since completion preflight')
        self.live_high_water = high_water
        for field, (container, image) in EXPECTED_COMPONENTS.items():
            if snapshot[field]['container_id'] != container or snapshot[field]['image_id'] != image:
                raise CompletionFailure('current component differs from latest observed attempt')
        require_unchanged(self.before, self.footprint())
        if any(self.launcher.digest(p) != value for p, value in self.input_hashes.items()):
            raise CompletionFailure('original audit or site configuration changed')
        self.recovery.check_partial_acquisition({
            'agent_health': [{'expected_bus_workers': EXPECTED_BUS_WORKERS}]})
        return snapshot

    def probe(self, profile, source, build):
        self.gateway.probe_frontend(PORTS[profile], source, build, self.gateway.origin_host(ORIGIN))

    def verify_restored(self):
        for profile in ('lan', 'protected'):
            if self.run('systemctl', 'show', UNITS[profile], '-p', 'WorkingDirectory', '--value') != str(OLD_RELEASES[profile]):
                raise CompletionFailure('restored frontend directory differs from exact prior identity')
            self.probe(profile, *OLD_IDENTITIES[profile])
        self.gateway.require_gateway_active(self.gateway.origin_host(ORIGIN))

    def write_identity(self, deployed_at):
        identity = {'schema_version': 'nexolab-runtime-identity-v1', 'service': 'dashboard',
                    'source_commit': TARGET, 'build_id': self.builds['lan'],
                    'identity_source': 'raspberry_activation', 'deployed_at': deployed_at}
        # Candidate and active manifests are separate immutable files. The active
        # unit never observes the candidate's null deployment timestamp.
        path = self.candidate_identity_path if deployed_at is None else self.identity_path
        self.recovery.atomic_json(path, identity)
        os.chown(path, self.owner.pw_uid, self.owner.pw_gid)
        if deployed_at is not None:
            self.recovery.atomic_json(self.audit / 'frontend-activation.json', {
                'schema_version': 1, 'kind': 'nexolab-frontend-completion-activation',
                'failed_attempt': self.context['stamp'], 'target_source': TARGET,
                'control_source': self.control, 'frontend_activated_at': deployed_at,
                'identity_manifest': str(path), 'identity_manifest_sha256': self.recovery.sha256_file(path)})
        self.frontend_activated_at = deployed_at

    def prepare_candidates(self):
        print('FRONTEND_COMPLETION_CURRENT_DATA_AND_LINEAGE_VERIFIED', flush=True)
        self.write_identity(None)
        for profile, port in (('lan', 3101), ('protected', 3102)):
            self.gateway.require_candidate_port(port)
            unit = 'nexolab-completion-' + profile + '-' + self.audit.name + '.service'
            release = self.releases[profile]
            env = ['--setenv=NODE_ENV=production', '--setenv=NEXT_TELEMETRY_DISABLED=1',
                   '--setenv=NEXOLAB_SERVER_API_BASE_URL=' + self.context['expected_contract']['api_base_url']]
            if profile == 'lan':
                env.append('--setenv=NEXOLAB_RUNTIME_IDENTITY_FILE=' + str(self.candidate_identity_path))
            else:
                env.append('--setenv=NEXOLAB_EXTERNAL_HTTPS_STAGE=true')
            started = True  # A timeout may happen after systemd accepted the unit.
            try:
                self.run('systemd-run', '--unit', unit, '--collect', '--service-type=exec',
                         '--property=User=nexolab', '--property=Group=nexolab',
                         '--property=WorkingDirectory=' + str(release), '--property=MemoryMax=768M',
                         '--property=MemorySwapMax=0', '--property=TasksMax=64',
                         '--property=NoNewPrivileges=yes', '--property=PrivateTmp=yes', *env,
                         str(self.node), str(release / 'node_modules/next/dist/bin/next'),
                         'start', '--hostname', '127.0.0.1', '--port', str(port))
                self.gateway.probe_frontend(port, TARGET, self.builds[profile], self.gateway.origin_host(ORIGIN))
                print('FRONTEND_COMPLETION_CANDIDATE_VERIFIED=' + profile, flush=True)
            finally:
                if started:
                    if self.run('systemctl', 'show', unit, '-p', 'LoadState', '--value') != 'not-found':
                        self.run('systemctl', 'stop', unit)
            self.gateway.require_candidate_port(port)
        self.gateway.require_gateway_active(self.gateway.origin_host(ORIGIN))
        self.check_data()

    def mark_started(self):
        marker = {
            'schema_version': 1, 'kind': 'nexolab-frontend-only-completion-started',
            'failed_attempt': ATTEMPT, 'control_source': self.control, 'target_source': TARGET,
            'completion_audit': str(self.audit), 'automatic_retry': False}
        filename = 'frontend-completion-started.json'
        if self.predecessor:
            filename = self.recovery.CONTRACT_CONTINUATION_MARKER
            marker.update(predecessor_audit=self.predecessor['frontend_completion']['audit'],
                          predecessor_report_sha256=self.recovery.CONTRACT_FAILURE_REPORT_SHA)
        path = self.failed / filename
        # The canonical deployment lock is held. Neither marker may be replaced.
        if path.exists() or path.is_symlink():
            raise CompletionFailure('completion marker already exists; no retry')
        self.recovery.atomic_json(path, marker)
        print('FRONTEND_COMPLETION_PAIRED_HANDOFF_STARTED; backend retained', flush=True)

    def switch(self, profile, candidate):
        self.run('systemctl', 'stop', UNITS[profile])
        file = self.audit / (profile + ('-unit-candidate.service' if candidate else '-unit-before.service'))
        self.run('install', '-m', '0644', str(file), '/etc/systemd/system/' + UNITS[profile])
        self.run('systemctl', 'daemon-reload')
        if profile == 'lan' and candidate:
            self.write_identity(datetime.now(timezone.utc).isoformat())
        self.run('systemctl', 'start', UNITS[profile])
        self.probe(profile, TARGET if candidate else OLD_IDENTITIES[profile][0],
                   self.builds[profile] if candidate else OLD_IDENTITIES[profile][1])
        if profile == 'protected':
            self.run('systemctl', 'start', 'nexolab-external-nginx.service', timeout=15)
            self.gateway.require_gateway_active(self.gateway.origin_host(ORIGIN))

    def activate(self, profile):
        self.switch(profile, True)
        print('FRONTEND_COMPLETION_ACTIVE_VERIFIED=' + profile, flush=True)

    def restore(self, profile):
        self.switch(profile, False)

    def verify_target(self):
        self.snapshot = self.check_data()
        self.recovery.validate_runtime_snapshot(self.snapshot, self.context)
        for profile in ('lan', 'protected'):
            if self.run('systemctl', 'show', UNITS[profile], '-p', 'WorkingDirectory', '--value') != str(self.releases[profile]):
                raise CompletionFailure('active frontend process directory differs from latest candidate')
            self.probe(profile, TARGET, self.builds[profile])
        identity = self.recovery._partial_http('127.0.0.1', PORTS['lan'], '/api/runtime-identity')
        if (not self.frontend_activated_at or identity.get('deployed_at') != self.frontend_activated_at
                or identity.get('identity_source') != 'raspberry_activation'):
            raise CompletionFailure('active frontend identity does not report the actual handoff time')
        self.gateway.require_gateway_active(self.gateway.origin_host(ORIGIN))

    def publish(self):
        context = self.recovery.frontend_completion_context(self.context, self.failed)
        expected = {'audit': str(self.audit), 'control_source': self.control,
            'external_frontend_origin': ORIGIN, 'external_frontend_source_commit': TARGET,
            'external_frontend_build_id': self.builds['protected'],
            'frontend_activated_at': self.frontend_activated_at,
            'backend_mutation_started_at': self.context['mutation_started_at'],
            'runtime_mutation': 'paired_frontends_only', 'backend_containers': 'unchanged'}
        if self.predecessor:
            expected['predecessor_audit'] = self.predecessor['frontend_completion']['audit']
        if context['frontend_completion'] != expected:
            raise CompletionFailure('paired completion publication evidence differs from verified handoff')
        result = self.recovery.build_frontend_completion_result(self.snapshot, context)
        self.recovery.validate_result(result, context)
        self.recovery.atomic_json(self.failed / self.recovery.RESULT_NAME, result)

    def publication_exists(self):
        return (self.failed / self.recovery.RESULT_NAME).exists()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control-source', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--continue-contract-failure', action='store_true',
                        help='Continue only the recorded 20261010T214443Z contract failure; retain its marker/audit')
    args = parser.parse_args()
    if (not re.fullmatch('[0-9a-f]{40}', args.control_source) or os.geteuid() != 0
            or os.environ.get('SUDO_USER') != 'nexolab' or platform.node() != 'nexolab-edge-01'
            or platform.machine() != 'aarch64'):
        print('Requires owner-local sudo on nexolab-edge-01 ARM64 and exact reviewed control.')
        return 64
    os.umask(0o077)
    owner = pwd.getpwnam('nexolab')
    descriptor, audit = None, None
    report = {'kind': 'nexolab-paired-frontend-completion', 'schema_version': 1,
              'status': 'stopped_unverified', 'automatic_retry': False,
              'failed_attempt': ATTEMPT, 'control_source': args.control_source,
              'started_at': datetime.now(timezone.utc).isoformat(), 'execute': args.execute}
    try:
        # First use only fixed owner Git commands; import helpers only after exact
        # reviewed checkout and self-verification, never from the staged directory.
        def owner_git(*arguments):
            return subprocess.run(['/usr/sbin/runuser', '--user', 'nexolab', '--', '/usr/bin/git',
                                   '--no-optional-locks', '-C', str(REPO), *arguments],
                                  check=True, capture_output=True, timeout=90).stdout
        for path in (REPO, REPO / '.git', REPO / '.git/index'):
            if path.is_symlink() or path.stat().st_uid != owner.pw_uid:
                raise CompletionFailure('repository owner or index identity differs')
        if owner_git('branch', '--show-current').strip() != b'main' or owner_git('status', '--porcelain', '--untracked-files=no').strip():
            raise CompletionFailure('clean owner main required')
        if owner_git('show', 'HEAD:scripts/deploy-partial-continuation-1327.py') != (REPO / 'scripts/deploy-partial-continuation-1327.py').read_bytes():
            raise CompletionFailure('existing lock helper is locally changed')
        launcher = load_helper('launcher_lock', 'deploy-partial-continuation-1327.py')
        descriptor, lock = launcher.acquire_existing_lock(launcher.LOCK, owner.pw_uid)
        owner_git('fetch', '--prune', 'origin', 'main')
        if owner_git('rev-parse', 'origin/main').strip().decode() != args.control_source:
            raise CompletionFailure('fresh main differs from reviewed control')
        if owner_git('show', args.control_source + ':scripts/deploy-complete-partial-frontends.py') != Path(__file__).read_bytes():
            raise CompletionFailure('staged tool differs from reviewed control')
        owner_git('merge', '--ff-only', args.control_source)
        launcher = load_helper('completion_launcher_utilities', 'deploy-partial-continuation-1327.py')
        owner_helper = load_helper('completion_owner', 'deploy-privileged-service-owner.py')
        owner_helper.context(REPO, 'nexolab')
        recovery = load_helper('completion_recovery', 'forward_deployment_recovery.py')
        recovery.git = lambda repo, *arguments: owner_git(*arguments).decode().strip()
        gateway = load_helper('completion_gateway', 'nexolab-protected-frontend.py')
        parent = REPO / 'runtime/frontend-completions'
        if parent.is_symlink():
            raise CompletionFailure('completion audit parent is unsafe')
        parent_existed = parent.exists()
        parent.mkdir(mode=0o700, exist_ok=True)
        if not parent_existed:
            os.chown(parent, owner.pw_uid, owner.pw_gid)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        audit = Path(tempfile.mkdtemp(prefix=stamp + '-', dir=parent))
        def interrupted(*_):
            raise CompletionFailure('owner completion interrupted')
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        report['failed_stage'] = 'latest_attempt_and_current_data_preflight'
        operations = Operations(args.control_source, audit, owner, launcher, recovery, gateway,
                                continue_contract_failure=args.continue_contract_failure)
        report['failed_stage'] = 'isolated_frontend_candidates'
        operations.prepare_candidates()
        launcher.verify_locked_inode(launcher.LOCK, descriptor, lock)
        if args.execute:
            report['failed_stage'] = 'paired_handoff_and_genuine_reconciliation'
            handoff(operations)
            report['status'] = 'paired_frontends_reconciled'
            report['frontend_activated_at'] = operations.frontend_activated_at
        else:
            report['status'] = 'frontend_candidates_and_current_data_verified_no_activation'
        launcher.verify_locked_inode(launcher.LOCK, descriptor, lock)
        report.pop('failed_stage', None)
    except Exception as error:
        report['status'] = 'stopped_unverified'
        report['error_type'] = type(error).__name__
        report['reason'] = str(error) if isinstance(error, CompletionFailure) else 'bounded operation failed; preserve private audit'
        if 'recovery' in locals() and isinstance(error, recovery.RecoveryFailure):
            report.update(recovery.partial_failure_details(error))
        if 'operations' in locals() and getattr(operations, 'restoration', None):
            report['frontend_restoration'] = operations.restoration
    finally:
        if descriptor is not None:
            os.close(descriptor)
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        if audit is not None:
            path = audit / 'report.json'
            with path.open('x') as stream:
                json.dump(report, stream, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
            os.chown(path, owner.pw_uid, owner.pw_gid)
            os.chown(audit, owner.pw_uid, owner.pw_gid)
            print('FRONTEND_COMPLETION_REPORT=' + str(path))
    print('FRONTEND_COMPLETION_' + report['status'].upper())
    if report['status'] == 'stopped_unverified':
        print('FRONTEND_COMPLETION_REASON=' + report.get('reason', 'preflight stopped'))
    return 0 if report['status'] != 'stopped_unverified' else 2


if __name__ == '__main__':
    raise SystemExit(main())
