#!/usr/bin/env python3
"""Reissue a pinned bundle with accepted storage and reviewed tooling, without builds."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.dont_write_bytecode = True


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-bundle', type=Path, required=True)
    parser.add_argument('--original-manifest-sha256', required=True)
    parser.add_argument('--storage-archive', type=Path, required=True)
    parser.add_argument('--storage-archive-sha256', required=True)
    parser.add_argument('--storage-reference', required=True)
    parser.add_argument('--storage-image-id', required=True)
    parser.add_argument('--storage-sbom-directory', type=Path, required=True)
    parser.add_argument('--tooling-commit', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    require(subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip() == args.tooling_commit,
            'Tooling checkout differs from reviewed commit')
    require(not subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain', '--untracked-files=no'], text=True),
            'Tooling checkout contains tracked changes')
    require(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,180}', args.version), 'Invalid distinct reissue version')
    original = args.original_bundle.resolve()
    output = args.output.resolve()
    require(not output.exists() and original not in output.parents, 'Reissue output must be new and separate')
    require(sha256(original / 'manifest.json') == args.original_manifest_sha256, 'Original manifest changed')
    require(sha256(args.storage_archive) == args.storage_archive_sha256, 'Accepted storage export changed')
    manifest = json.loads((original / 'manifest.json').read_text())
    require(args.version != manifest['bundle_version'], 'Reissue must have a distinct version')
    subprocess.run([sys.executable, str(original / 'scripts/verify-offline-bundle.py'), str(original)], check=True)
    spec = importlib.util.spec_from_file_location('archive', repo / 'scripts/offline_image_archive.py')
    archive = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(archive)
    original_tar = original / manifest['images_archive']['path']
    before = archive.archive_identities(original_tar, manifest['images'], manifest['platform'])
    for image in manifest['images']:
        require(image['image_id'] in before[image['id']]['runtime_digests'], 'Original image inventory differs from archive')
    with archive.ImageArchive(args.storage_archive) as saved:
        accepted = saved.identity(args.storage_reference, manifest['platform'])
        require(args.storage_image_id in accepted['runtime_digests'], 'Storage export differs from accepted migration image')
    accepted_inspect = json.loads(subprocess.check_output(['docker', 'image', 'inspect', args.storage_image_id], text=True))
    require(isinstance(accepted_inspect, list) and len(accepted_inspect) == 1, 'Accepted native storage image is unavailable')
    archive.check_loaded_identity(accepted_inspect[0], accepted, manifest['platform'])
    require(accepted_inspect[0]['Id'] == args.storage_image_id, 'Accepted storage runtime digest changed')
    sbom_files = []
    for suffix in ('cdx.json', 'spdx.json'):
        path = args.storage_sbom_directory / ('object-storage.' + suffix)
        payload = json.loads(path.read_text())
        require(payload.get('bomFormat') == 'CycloneDX' if suffix == 'cdx.json' else str(payload.get('spdxVersion', '')).startswith('SPDX-'),
                'Invalid accepted storage SBOM')
        # Trivy records the actual scanned config digest in both SBOM formats.
        require(accepted['config_digest'].split(':')[1] in path.read_text(), 'SBOM is not bound to accepted storage config')
        sbom_files.append(path)
    original_provenance = json.loads((original / 'evidence/provenance.json').read_text())
    original_files = {r['path']: r['sha256'] for r in manifest['files']}
    require(all(not p.is_symlink() for p in original.rglob('*')), 'Original bundle contains symlinks')
    shutil.copytree(original, output, ignore=lambda directory, names: [name for name in names
                    if (Path(directory) / name).relative_to(original).as_posix() in {manifest['images_archive']['path'], '.nexolab-validated.json'}])
    merged = output / manifest['images_archive']['path']
    identities = archive.merge_archives(original_tar, args.storage_archive, manifest['images'],
                                       args.storage_reference, manifest['platform'], merged)
    for path in (output / 'scripts').rglob('*'):
        if path.is_file():
            source = repo / path.relative_to(output)
            require(source.is_file(), 'Reviewed tooling file missing: ' + str(source))
            shutil.copyfile(source, path)
    shutil.copyfile(repo / 'scripts/offline_image_archive.py', output / 'scripts/offline_image_archive.py')
    for path in sbom_files:
        shutil.copyfile(path, output / 'evidence' / path.name)
    provenance = copy.deepcopy(original_provenance)
    provenance.update(tooling_commit=args.tooling_commit, bundle_version=args.version,
                      builder='scripts/reissue-offline-bundle.py', created_at=datetime.now(UTC).isoformat())
    provenance['tooling_capabilities'] = sorted(set(provenance['tooling_capabilities']) | {'portable-image-identity', 'fail-closed-image-import', 'retained-storage-preflight'})
    provenance['reissue'] = {'original_manifest_sha256': args.original_manifest_sha256,
                            'original_images_archive_sha256': manifest['images_archive']['sha256'],
                            'original_bundle_id': manifest['version_management']['bundle_id'],
                            'original_provenance': original_provenance,
                            'accepted_storage_runtime_digest': args.storage_image_id,
                            'accepted_storage_export_sha256': args.storage_archive_sha256,
                            'application_image_builds': 0, 'manual_workflow_dispatches': 0}
    write_json(output / 'evidence/provenance.json', provenance)
    manifest['bundle_version'] = args.version
    manifest['version_management']['bundle_id'] = args.version + '-' + manifest['source_commit'][:12]
    manifest['created_at'] = provenance['created_at']
    for image in manifest['images']:
        image['identity'] = identities[image['id']]
        image['image_id'] = image['identity']['config_digest']
        if image['id'] == 'object-storage':
            image['reference'] = args.storage_reference
            image['repo_digests'] = []
            image['size_bytes'] = int(accepted_inspect[0]['Size'])
            for evidence in image['sbom'].values():
                evidence['sha256'] = sha256(output / evidence['path'])
        else:
            require(image['identity'] == before[image['id']], 'Application image bytes/identity changed')
    manifest['images_archive'].update(sha256=sha256(merged), size_bytes=merged.stat().st_size)
    manifest['files'] = [{'path': p.relative_to(output).as_posix(), 'sha256': sha256(p), 'size_bytes': p.stat().st_size}
                         for p in sorted(output.rglob('*')) if p.is_file() and p.relative_to(output).as_posix() not in {'manifest.json', 'SHA256SUMS'}]
    write_json(output / 'manifest.json', manifest)
    (output / 'SHA256SUMS').write_text(''.join(sha256(p) + '  ' + p.relative_to(output).as_posix() + '\n'
          for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS'))
    require(sha256(original / 'manifest.json') == args.original_manifest_sha256 and
            all(sha256(original / name) == digest for name, digest in original_files.items()), 'Original bundle changed')
    subprocess.run([sys.executable, str(output / 'scripts/verify-offline-bundle.py'), str(output)], check=True)
    print(json.dumps({'status': 'reissued_not_activated', 'bundle_id': manifest['version_management']['bundle_id'],
                      'manifest_sha256': sha256(output / 'manifest.json'), 'output': str(output)}, sort_keys=True))


if __name__ == '__main__':
    main()
