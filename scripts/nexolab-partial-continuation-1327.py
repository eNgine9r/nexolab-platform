#!/usr/bin/env python3
"""One owner-local, data-preserving partial continuation for nexolab-edge-01.

Requires the reviewed merged control commit explicitly. No automatic retries.
Canonical private evidence and lock are read as root; all Git uses nexolab.
"""
from __future__ import annotations

from datetime import datetime, timezone
import argparse
import fcntl
import stat
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import re
import subprocess
import sys
import tempfile

REPO = Path('/home/nexolab/nexolab-platform')
STAGE = Path('/home/nexolab/commander-workspaces/nexolab-platform/guarded-update-1313-df5485f6')
LOCK = Path('/tmp/nexolab-current-head-launch.lock')
RUNUSER = '/usr/sbin/runuser'
GIT = '/usr/bin/git'
TARGET = 'c296c58f3cb2b221b88a8d4e9d6a4cf67e5e33e2'
PREVIOUS = 'd00a83bfc83fb120777c721b5e46fa50ae455c7d'
CAPTURE = STAGE / 'runtime-check-1323-4j0c_0ij/report.json'
CAPTURE_SHA = '45b29478615b520344d5fba2b8748bfd42c7a81ec17d3ad24daedea3fdeba71f'
RECOVERY = STAGE / 'agent-recovery-1321-6vfd0nw3/report.json'
RECOVERY_SHA = '9217195791d467413608bb9976a1c3e55f64d0c6699ab9c287af0e38379917f5'
ORIGIN = 'https://nexolab-edge-01.tail7f9b04.ts.net'
ARTIFACTS = {'lan': {'directory': '/home/nexolab/commander-workspaces/nexolab-platform/guarded-update-1313-df5485f6/artifacts/nexolab-frontend-release-c296c58f3cb2b221b88a8d4e9d6a4cf67e5e33e2-arm64', 'inventory_sha256': '52d06c3b75276c3c3a48c4849c24295e5725e1808415027933685b937bc6367a', 'build_id': 'Ar6aVrTWJICF6TKFaWxHw'}, 'protected': {'directory': '/home/nexolab/commander-workspaces/nexolab-platform/guarded-update-1313-df5485f6/artifacts/nexolab-external-frontend-release-c296c58f3cb2b221b88a8d4e9d6a4cf67e5e33e2-arm64', 'inventory_sha256': 'd81b999360e174845974d6292444edc2090b08be97422d5b91e15bbd001b344c', 'build_id': 'mcG0fHLcpCeVbTX--85gF'}}


def digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('required regular file is unavailable')
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_artifact(profile: str) -> Path:
    pin = ARTIFACTS[profile]
    directory = Path(pin['directory'])
    if directory.is_symlink() or not directory.is_dir():
        raise RuntimeError('prepared artifact directory is unavailable')
    inventory = directory / 'frontend-artifact-sha256.txt'
    if digest(inventory) != pin['inventory_sha256']:
        raise RuntimeError('prepared artifact inventory pin changed')
    expected = {'frontend-runtime.tar.gz', 'package.json', 'package-lock.json',
                'frontend-source-sha.txt', 'frontend-package-sha256.txt',
                'frontend-runtime-contract.txt', 'frontend-platform.txt',
                'frontend-node-version.txt', 'frontend-build-id.txt',
                'frontend-runtime-files-sha256.txt', 'frontend-public-contract.txt',
                'frontend-native-files.txt'}
    rows = inventory.read_text().splitlines()
    names = []
    for row in rows:
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9.-]+)', row)
        if not match or match[2] not in expected or match[2] in names:
            raise RuntimeError('prepared artifact inventory is malformed')
        names.append(match[2])
        if digest(directory / match[2]) != match[1]:
            raise RuntimeError('prepared artifact file checksum mismatch')
    if set(names) != expected:
        raise RuntimeError('prepared artifact inventory is incomplete')
    if (directory / 'frontend-source-sha.txt').read_text().strip() != TARGET:
        raise RuntimeError('prepared artifact source differs from failed target')
    if (directory / 'frontend-platform.txt').read_text().strip() != 'linux/arm64':
        raise RuntimeError('prepared artifact platform differs from actual host')
    if (directory / 'frontend-build-id.txt').read_text().strip() != pin['build_id']:
        raise RuntimeError('prepared artifact build identity changed')
    return directory


def lock_identity(value: os.stat_result) -> dict:
    return {'uid': value.st_uid, 'gid': value.st_gid, 'mode': oct(stat.S_IMODE(value.st_mode)),
            'device': value.st_dev, 'inode': value.st_ino, 'bytes': value.st_size}


def acquire_existing_lock(path: Path, owner_uid: int) -> tuple[int, dict]:
    """Linux flock works on an existing read descriptor; no create/truncate."""
    parent = path.parent.stat(follow_symlinks=False)
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0
        or (stat.S_IMODE(parent.st_mode) & 0o022 and not parent.st_mode & stat.S_ISVTX)):
        raise ValueError('unsafe_canonical_lock_parent')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        value = os.fstat(descriptor)
        if (not stat.S_ISREG(value.st_mode) or value.st_nlink != 1 or value.st_size != 0
            or value.st_uid not in (0, owner_uid) or stat.S_IMODE(value.st_mode) != 0o600):
            raise ValueError('unexpected_existing_lock_identity')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        observed = os.lstat(path)
        if (observed.st_dev, observed.st_ino) != (value.st_dev, value.st_ino):
            raise ValueError('canonical_lock_replaced')
        return descriptor, lock_identity(value)
    except BaseException:
        os.close(descriptor)
        raise


def verify_locked_inode(path: Path, descriptor: int, before: dict) -> None:
    if lock_identity(os.fstat(descriptor)) != before or lock_identity(os.lstat(path)) != before:
        raise ValueError('canonical_lock_identity_changed')


def environment(node_bin: Path | None = None) -> dict:
    return {'PATH': ':'.join(([str(node_bin)] if node_bin else []) +
                            ['/usr/sbin', '/usr/bin', '/sbin', '/bin']),
            'LANG': 'C.UTF-8', 'NEXOLAB_REPO': str(REPO), 'XDG_RUNTIME_DIR': '/tmp',
            'SUDO_USER': 'nexolab', 'PYTHONDONTWRITEBYTECODE': '1',
            'GIT_OPTIONAL_LOCKS': '0'}


def owner_git(*arguments: str, timeout: int = 90) -> bytes:
    return subprocess.run([RUNUSER, '--user', 'nexolab', '--', GIT,
                           '--no-optional-locks', '-C', str(REPO), *arguments],
                          env=environment(), cwd=REPO, capture_output=True,
                          timeout=timeout, check=True).stdout


def command(control: str, lan: Path, protected: Path) -> list[str]:
    return ['/usr/bin/timeout', '--kill-after=30s', '2400s', '/bin/bash',
            str(REPO / 'scripts/deploy-current-head-raspberry-pi.sh'),
            '--runtime-mode', 'lan', '--source-ref', TARGET,
            '--expected-deployed-source', PREVIOUS, '--expected-control-source', control,
            '--preserve-service-owner', 'nexolab',
            '--continue-partial-activation', str(REPO / 'runtime/deployments/20261009T155213Z'),
            '--runtime-check-report', str(CAPTURE), '--runtime-check-sha256', CAPTURE_SHA,
            '--verified-agent-recovery-report', str(RECOVERY),
            '--frontend-artifact', str(lan), '--external-frontend-artifact', str(protected),
            '--external-origin', ORIGIN]


def verify_success(output: str, control: str) -> Path:
    # The deployer is the only authority. A zero exit or health-only probe cannot
    # substitute for its genuine durable final-state publication.
    matches = re.findall(r'^\[[^\n]+\] Evidence: (.+)$', output, re.MULTILINE)
    if not matches or len(set(matches)) != 1 or not re.search(r'^\[[^\n]+\] DEPLOYMENT PASSED$', output, re.MULTILINE):
        raise ValueError('genuine_deployment_success_missing')
    audit = Path(matches[0])
    if audit.parent != REPO / 'runtime/deployments' or not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z', audit.name):
        raise ValueError('unexpected_new_deployment_evidence')
    values = {}
    for row in (audit / 'final-state.txt').read_text().split('\n\n', 1)[0].splitlines():
        if '=' in row:
            key, value = row.split('=', 1)
            if key in values:
                raise ValueError('duplicate_final_state_field')
            values[key] = value
    expected = {'commit': TARGET, 'control_origin_main': control,
                'frontend_build_id': ARTIFACTS['lan']['build_id'],
                'external_frontend_source_commit': TARGET,
                'external_frontend_build_id': ARTIFACTS['protected']['build_id'],
                'external_frontend_origin': ORIGIN}
    if any(values.get(key) != value for key, value in expected.items()):
        raise ValueError('new_deployment_identity_mismatch')
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control-source', required=True)
    args = parser.parse_args()
    control = args.control_source
    if (not re.fullmatch(r'[0-9a-f]{40}', control) or os.geteuid() != 0
            or os.environ.get('SUDO_USER') != 'nexolab'
            or platform.node() != 'nexolab-edge-01' or platform.machine() != 'aarch64'):
        print('Requires sudo from nexolab on nexolab-edge-01 ARM64 and exact reviewed control.', file=sys.stderr)
        return 64
    if STAGE.is_symlink() or not STAGE.is_dir() or REPO.is_symlink():
        return 64
    os.umask(0o077)
    owner = pwd.getpwnam('nexolab')
    directory = Path(tempfile.mkdtemp(prefix='partial-continuation-1327-', dir=STAGE))
    report = {'kind': 'nexolab-owner-preserved-partial-continuation', 'schema_version': 1,
              'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'stopped_unverified',
              'control_source': control, 'target_source': TARGET, 'previous_authority': PREVIOUS,
              'automatic_retry': False, 'database_restore': 'none', 'package_authority': 'not_modified',
              'log_path': str(directory / 'continuation.log')}
    descriptor = None
    phase = 'immutable_reports_and_artifacts'
    try:
        if digest(CAPTURE) != CAPTURE_SHA or digest(RECOVERY) != RECOVERY_SHA:
            raise ValueError('immutable_report_pin_changed')
        lan, protected = verify_artifact('lan'), verify_artifact('protected')
        phase = 'existing_canonical_lock'
        descriptor, facts = acquire_existing_lock(LOCK, owner.pw_uid)
        if descriptor != 9:
            os.dup2(descriptor, 9)
            os.close(descriptor)
            descriptor = 9
        report['canonical_lock_before'] = facts
        phase = 'owner_reviewed_main'
        if owner_git('branch', '--show-current').strip() != b'main':
            raise ValueError('clean_main_required')
        owner_git('diff', '--quiet')
        owner_git('diff', '--cached', '--quiet')
        index = REPO / '.git/index'
        if index.is_symlink() or index.stat().st_uid != owner.pw_uid:
            raise ValueError('owner_git_index_required')
        owner_git('fetch', '--prune', 'origin', 'main')
        if owner_git('rev-parse', 'origin/main').strip().decode() != control:
            raise ValueError('fresh_main_differs_from_reviewed_control')
        tracked_launcher = owner_git('show', control + ':scripts/nexolab-partial-continuation-1327.py')
        if Path(__file__).read_bytes() != tracked_launcher:
            raise ValueError('launcher_differs_from_reviewed_control')
        owner_git('merge', '--ff-only', control)
        if owner_git('rev-parse', 'HEAD').strip().decode() != control:
            raise ValueError('reviewed_control_not_checked_out')
        node_version = (REPO / '.nvmrc').read_text().strip()
        if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', node_version):
            raise ValueError('invalid_reviewed_node_version')
        node_bin = Path('/home/nexolab/.nvm/versions/node') / ('v' + node_version) / 'bin'
        if not (node_bin / 'node').is_file():
            raise ValueError('reviewed_node_unavailable')
        phase = 'single_full_partial_continuation'
        verify_locked_inode(LOCK, descriptor, facts)
        child_env = environment(node_bin)
        child_env['NEXOLAB_INHERITED_DEPLOYMENT_LOCK_FD'] = '9'
        with (directory / 'continuation.log').open('x') as log:
            result = subprocess.run(command(control, lan, protected), cwd=REPO,
                                    env=child_env, pass_fds=(9,), stdout=log, stderr=log,
                                    timeout=2440, check=False)
        report['deployer_returncode'] = result.returncode
        phase = 'lock_owner_and_genuine_final_state'
        verify_locked_inode(LOCK, descriptor, facts)
        report['canonical_lock_after'] = lock_identity(os.lstat(LOCK))
        if (owner_git('branch', '--show-current').strip() != b'main'
                or owner_git('rev-parse', 'HEAD').strip().decode() != control
                or index.stat().st_uid != owner.pw_uid):
            raise ValueError('owner_reviewed_main_not_preserved')
        owner_git('diff', '--quiet')
        owner_git('diff', '--cached', '--quiet')
        if result.returncode != 0:
            raise ValueError('full_continuation_stopped_no_automatic_retry')
        audit = verify_success((directory / 'continuation.log').read_text(), control)
        report['new_deployment_evidence'] = str(audit)
        report['status'] = 'source_continuation_verified'
        report['offline_package_install_update_rollback'] = 'not_yet_verified'
    except Exception as error:
        report['failed_stage'] = phase
        report['error_type'] = type(error).__name__
        report['reason'] = str(error) if isinstance(error, ValueError) else 'bounded operation failed; inspect private log'
    finally:
        if descriptor is not None:
            os.close(descriptor)
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        with (directory / 'report.json').open('x') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        for path in directory.iterdir():
            if path.is_file() and not path.is_symlink():
                os.chown(path, owner.pw_uid, owner.pw_gid)
        os.chown(directory, owner.pw_uid, owner.pw_gid)
    print('PARTIAL_CONTINUATION_REPORT=' + str(directory / 'report.json'))
    print('PARTIAL_CONTINUATION_' + ('VERIFIED' if report['status'] == 'source_continuation_verified' else 'STOPPED'))
    return 0 if report['status'] == 'source_continuation_verified' else 2


if __name__ == '__main__':
    raise SystemExit(main())

