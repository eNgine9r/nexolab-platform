from __future__ import annotations

import importlib.util
import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), SCRIPTS / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_containerd_identity_is_verified_from_archive_not_config_id_only():
    verifier = load('verify-offline-bundle.py')
    image = {'reference': 'example/app:one', 'image_id': 'sha256:' + '1' * 64,
             'platform': 'linux/arm64', 'identity': {'config_digest': 'sha256:' + '1' * 64,
             'runtime_digests': ['sha256:' + '1' * 64, 'sha256:' + '2' * 64],
             'diff_ids': ['sha256:' + '3' * 64]}}
    actual = {'Id': 'sha256:' + '2' * 64, 'Os': 'linux', 'Architecture': 'arm64',
              'RootFS': {'Layers': image['identity']['diff_ids']}}
    with patch.object(verifier.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps([actual]), '')):
        verifier.inspect_loaded_images({'dashboard': image})


def test_installer_propagates_loaded_verifier_failure_before_compose(tmp_path):
    bundle = tmp_path / 'bundle'
    (bundle / 'scripts/lib').mkdir(parents=True)
    shutil.copyfile(SCRIPTS / 'install-offline-bundle.sh', bundle / 'scripts/install-offline-bundle.sh')
    shutil.copyfile(SCRIPTS / 'lib/deployment-lock.sh', bundle / 'scripts/lib/deployment-lock.sh')
    (bundle / 'scripts/verify-offline-bundle.py').write_text(
        "import sys\nif '--check-loaded-images' in sys.argv: raise SystemExit(19)\n")
    fake_bin = tmp_path / 'bin'
    fake_bin.mkdir()
    docker = fake_bin / 'docker'
    docker.write_text('#!/bin/sh\necho "$*" >> "$DOCKER_LOG"\nexit 0\n')
    docker.chmod(0o755)
    central = tmp_path / 'central.env'
    central.write_text('')
    log = tmp_path / 'docker.log'
    result = subprocess.run(['bash', str(bundle / 'scripts/install-offline-bundle.sh'),
                             '--central-env', str(central), '--skip-edge', '--preflight-only'],
                            env={**os.environ, 'PATH': f'{fake_bin}:{os.environ["PATH"]}',
                                 'XDG_RUNTIME_DIR': str(tmp_path), 'DOCKER_LOG': str(log),
                                 'OFFLINE_OBJECT_STORAGE_IMAGE': 'inherited:wrong'},
                            capture_output=True, text=True)
    assert result.returncode == 19, result.stderr
    assert log.read_text().splitlines() == ['compose version', f'load --input {bundle}/images/nexolab-images.tar']


def make_archive(path, reference='example/app:one', *, oci=True, index=False, compressed=False, layer=b'app-layer', duplicate=False):
    module = load('offline_image_archive.py')
    blobs = {}
    def blob(value, media):
        if isinstance(value, dict):
            value = json.dumps(value, separators=(',', ':')).encode()
        digest = module.digest_bytes(value)
        blobs['blobs/sha256/' + digest.split(':')[1]] = value
        return {'mediaType': media, 'digest': digest, 'size': len(value)}
    diff = module.digest_bytes(layer)
    layer_descriptor = blob(gzip.compress(layer) if compressed else layer,
                            'application/vnd.oci.image.layer.v1.tar' + ('+gzip' if compressed else ''))
    config = blob({'architecture': 'arm64', 'os': 'linux', 'rootfs': {'type': 'layers', 'diff_ids': [diff]}},
                  'application/vnd.oci.image.config.v1+json')
    manifest = blob({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                     'config': config, 'layers': [layer_descriptor]}, 'application/vnd.oci.image.manifest.v1+json')
    root = manifest
    if index:
        manifest['platform'] = {'os': 'linux', 'architecture': 'arm64'}
        root = blob({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json',
                     'manifests': [manifest]}, 'application/vnd.oci.image.index.v1+json')
    root['annotations'] = {'io.containerd.image.name': 'docker.io/' + reference}
    blobs['manifest.json'] = json.dumps([{'Config': 'blobs/sha256/' + config['digest'].split(':')[1],
                                         'RepoTags': [reference], 'Layers': ['blobs/sha256/' + layer_descriptor['digest'].split(':')[1]]}]).encode()
    if oci:
        blobs['index.json'] = json.dumps({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json', 'manifests': [root]}).encode()
    with tarfile.open(path, 'w') as target:
        for name, data in blobs.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            target.addfile(member, io.BytesIO(data))
        if duplicate:
            member = tarfile.TarInfo('manifest.json')
            member.size = len(blobs['manifest.json'])
            target.addfile(member, io.BytesIO(blobs['manifest.json']))
    return config['digest'], root['digest'], diff, blobs


@pytest.mark.parametrize('oci,index,compressed', [(False, False, False), (True, False, False), (True, True, True)])
def test_archive_proves_config_descriptor_and_layers(tmp_path, oci, index, compressed):
    module = load('offline_image_archive.py')
    path = tmp_path / 'image.tar'
    config, root, diff, _ = make_archive(path, oci=oci, index=index, compressed=compressed)
    with module.ImageArchive(path) as saved:
        identity = saved.identity('example/app:one', 'linux/arm64')
    assert identity['config_digest'] == config
    assert identity['diff_ids'] == [diff]
    assert (root in identity['runtime_digests']) is oci
    for native in identity['runtime_digests']:
        module.check_loaded_identity({'Id': native, 'Os': 'linux', 'Architecture': 'arm64',
                                      'RootFS': {'Layers': [diff]}}, identity, 'linux/arm64')
    if oci:
        module.check_loaded_identity({'Id': config, 'Descriptor': {'digest': root},
                                      'Os': 'linux', 'Architecture': 'arm64',
                                      'RootFS': {'Layers': [diff]}}, identity, 'linux/arm64')
        for unproven in (config, 'sha256:' + 'f' * 64):
            with pytest.raises(ValueError, match='descriptor is not proven'):
                module.check_loaded_identity({'Id': config, 'Descriptor': {'digest': unproven},
                                              'Os': 'linux', 'Architecture': 'arm64',
                                              'RootFS': {'Layers': [diff]}}, identity, 'linux/arm64')
    with pytest.raises(ValueError, match='ID mismatch'):
        module.check_loaded_identity({'Id': 'sha256:' + 'f' * 64, 'Os': 'linux', 'Architecture': 'arm64',
                                      'RootFS': {'Layers': [diff]}}, identity, 'linux/arm64')


@pytest.mark.parametrize('change', ['duplicate', 'layer', 'config', 'platform', 'ambiguous', 'symlink', 'traversal'])
def test_archive_rejects_unproven_or_unsafe_identity(tmp_path, change):
    module = load('offline_image_archive.py')
    path = tmp_path / 'image.tar'
    config, _, _, blobs = make_archive(path, duplicate=change == 'duplicate')
    if change in {'layer', 'config', 'ambiguous'}:
        if change == 'ambiguous':
            payload = json.loads(blobs['index.json'])
            payload['manifests'].append(payload['manifests'][0])
            blobs['index.json'] = json.dumps(payload).encode()
        else:
            name = 'blobs/sha256/' + config.split(':')[1] if change == 'config' else next(n for n, b in blobs.items() if b == b'app-layer')
            blobs[name] += b'tampered'
        with tarfile.open(path, 'w') as target:
            for name, data in blobs.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                target.addfile(member, io.BytesIO(data))
    if change in {'symlink', 'traversal'}:
        with tarfile.open(path, 'a') as target:
            member = tarfile.TarInfo('../outside' if change == 'traversal' else 'alias')
            if change == 'symlink':
                member.type, member.linkname = tarfile.SYMTYPE, '/etc/passwd'
            target.addfile(member)
    with pytest.raises((ValueError, json.JSONDecodeError)):
        with module.ImageArchive(path) as saved:
            saved.identity('example/app:one', 'linux/amd64' if change == 'platform' else 'linux/arm64')


def test_merge_retains_app_bytes_and_accepted_index_without_old_storage(tmp_path):
    module = load('offline_image_archive.py')
    original, storage, output = [tmp_path / name for name in ('original.tar', 'storage.tar', 'reissued.tar')]
    app_config, _, _, before = make_archive(original)
    accepted_config, accepted_root, _, accepted_blobs = make_archive(storage, 'example/storage:accepted', index=True, compressed=True, layer=b'accepted-storage')
    original_sha = hashlib.sha256(original.read_bytes()).hexdigest()
    images = [{'id': 'dashboard', 'reference': 'example/app:one'}, {'id': 'object-storage', 'reference': 'example/storage:old'}]
    identities = module.merge_archives(original, storage, images, 'example/storage:accepted', 'linux/arm64', output)
    assert identities['dashboard']['config_digest'] == app_config
    assert identities['object-storage']['config_digest'] == accepted_config
    assert accepted_root in identities['object-storage']['runtime_digests']
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_sha
    with module.ImageArchive(output) as saved:
        assert saved.identity('example/app:one', 'linux/arm64') == identities['dashboard']
        assert saved.identity('example/storage:accepted', 'linux/arm64') == identities['object-storage']
        for name, data in before.items():
            if name.startswith('blobs/'):
                assert saved.tar.extractfile(name).read() == data
        with pytest.raises(ValueError, match='Missing or ambiguous'):
            saved.identity('example/storage:old', 'linux/arm64')
    with pytest.raises(FileExistsError):
        module.merge_archives(original, storage, images, 'example/storage:accepted', 'linux/arm64', output)


@pytest.mark.parametrize('volume_suffix', ['-object-storage-data', '-object-storage-versitygw-data'])
def test_custom_compose_storage_is_rejected_before_import_or_migration(tmp_path, volume_suffix):
    verifier = load('verify-offline-bundle.py')
    env = tmp_path / 'central.env'
    env.write_text('COMPOSE_PROJECT_NAME="site-a"\n')
    resolved = {'volumes': {'central-object-storage-data': {'name': 'site-a-object-storage-versitygw-data'}}}
    with patch.object(verifier.subprocess, 'run', side_effect=[
        subprocess.CompletedProcess([], 0, json.dumps(resolved), ''),
        subprocess.CompletedProcess([], 0, 'site-a' + volume_suffix + '\n', ''),
    ]) as run:
        with pytest.raises(SystemExit, match='custom resource prefix'):
            verifier.verify_site_storage(tmp_path, {}, {}, env, tmp_path)
    assert run.call_args_list[0].args[0] == ['docker', 'compose', '--env-file', str(env),
                                            '-f', str(tmp_path / 'deploy/compose/compose.central.yaml'),
                                            'config', '--format', 'json']
    assert run.call_args_list[1].args[0] == ['docker', 'volume', 'ls', '--format', '{{.Name}}']
    assert run.call_count == 2


@pytest.mark.parametrize('name', [None, 'unrecognized-volume', '${PREFIX}-object-storage-data'])
def test_unresolved_compose_storage_fails_before_volume_lookup(tmp_path, name):
    verifier = load('verify-offline-bundle.py')
    config = {'volumes': {'central-object-storage-data': {'name': name}}}
    with patch.object(verifier.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(config), '')) as run:
        with pytest.raises(SystemExit):
            verifier.verify_site_storage(tmp_path, {}, {}, tmp_path / 'env', tmp_path)
    assert run.call_count == 1


def test_failed_compose_resolution_is_not_treated_as_a_fresh_site(tmp_path):
    verifier = load('verify-offline-bundle.py')
    with patch.object(verifier.subprocess, 'run', side_effect=subprocess.CalledProcessError(2, ['docker', 'compose'])) as run:
        with pytest.raises(subprocess.CalledProcessError):
            verifier.verify_site_storage(tmp_path, {}, {}, tmp_path / 'env', tmp_path)
    assert run.call_count == 1


def test_fresh_resolved_storage_without_retained_volumes_is_allowed(tmp_path):
    verifier = load('verify-offline-bundle.py')
    config = {'volumes': {'central-object-storage-data': {'name': 'fresh-object-storage-versitygw-data'}}}
    with patch.object(verifier.subprocess, 'run', side_effect=[
        subprocess.CompletedProcess([], 0, json.dumps(config), ''),
        subprocess.CompletedProcess([], 0, '', ''),
    ]) as run:
        verifier.verify_site_storage(tmp_path, {}, {}, tmp_path / 'env', tmp_path)
    assert run.call_count == 2
