"""Prove Docker save config and OCI identities without extracting image layers."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path, PurePosixPath

DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')
INDEX_TYPES = {'application/vnd.oci.image.index.v1+json', 'application/vnd.docker.distribution.manifest.list.v2+json'}
MANIFEST_TYPES = {'application/vnd.oci.image.manifest.v1+json', 'application/vnd.docker.distribution.manifest.v2+json'}
LAYER_TYPES = {'application/vnd.oci.image.layer.v1.tar', 'application/vnd.oci.image.layer.v1.tar+gzip',
               'application/vnd.docker.image.rootfs.diff.tar', 'application/vnd.docker.image.rootfs.diff.tar.gzip'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest_bytes(value):
    return 'sha256:' + hashlib.sha256(value).hexdigest()


def digest_stream(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
    return 'sha256:' + digest.hexdigest()


def normalized_reference(reference):
    if reference.startswith('docker.io/'):
        reference = reference[len('docker.io/'):]
    if '/' not in reference:
        reference = 'library/' + reference
    return reference


class ImageArchive:
    def __init__(self, path):
        self.tar = tarfile.open(path, 'r:')
        self.members = {}
        self.checked = {}
        try:
            for member in self.tar:
                name = member.name.rstrip('/') if member.isdir() else member.name
                p = PurePosixPath(name)
                require(name and not p.is_absolute() and '..' not in p.parts and str(p) == name,
                        'Unsafe image archive member')
                require(name not in self.members, 'Duplicate image archive member: ' + name)
                require(member.isfile() or member.isdir(), 'Image archive links/devices are forbidden')
                self.members[name] = member
            self.records = self.json('manifest.json')
            require(isinstance(self.records, list), 'Invalid Docker save manifest')
            self.index = self.json('index.json') if 'index.json' in self.members else None
            if self.index is not None:
                require(self.index.get('schemaVersion') == 2 and isinstance(self.index.get('manifests'), list),
                        'Invalid OCI index')
        except BaseException:
            self.tar.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.tar.close()

    def member(self, name):
        require(name in self.members and self.members[name].isfile(), 'Missing image archive file: ' + str(name))
        return self.members[name]

    def read(self, name):
        member = self.member(name)
        require(member.size <= 4 * 1024 * 1024, 'Image metadata exceeds limit')
        with self.tar.extractfile(member) as stream:
            return stream.read()

    def json(self, name):
        return json.loads(self.read(name))

    def check_descriptor(self, descriptor):
        require(isinstance(descriptor, dict) and DIGEST.fullmatch(str(descriptor.get('digest', ''))),
                'Invalid OCI digest')
        digest = descriptor['digest']
        name = 'blobs/sha256/' + digest.split(':')[1]
        member = self.member(name)
        require(type(descriptor.get('size')) is int and member.size == descriptor['size'], 'OCI blob size mismatch')
        if digest not in self.checked:
            with self.tar.extractfile(member) as stream:
                require(digest_stream(stream) == digest, 'OCI blob checksum mismatch')
            self.checked[digest] = name
        return name

    def platform_manifest(self, descriptor, platform, depth=0):
        require(depth <= 4, 'OCI index nesting exceeds limit')
        payload = self.json(self.check_descriptor(descriptor))
        require(payload.get('schemaVersion') == 2, 'Invalid OCI schema')
        media = descriptor.get('mediaType')
        if media in MANIFEST_TYPES:
            require(payload.get('mediaType', media) == media, 'OCI media type mismatch')
            return descriptor, payload
        require(media in INDEX_TYPES and payload.get('mediaType', media) == media, 'Unsupported OCI descriptor')
        entries = payload.get('manifests')
        require(isinstance(entries, list), 'Invalid OCI manifest list')
        candidates = []
        for item in entries:
            self.check_descriptor(item)
            declared = item.get('platform', {})
            if declared.get('os', '') + '/' + declared.get('architecture', '') == platform:
                candidates.append(item)
            else:
                require(declared.get('os') == 'unknown' and declared.get('architecture') == 'unknown',
                        'Unexpected platform in single-platform offline image')
        require(len(candidates) == 1, 'Missing or ambiguous OCI platform')
        return self.platform_manifest(candidates[0], platform, depth + 1)

    def identity(self, reference, platform):
        records = [r for r in self.records if reference in (r.get('RepoTags') or [])]
        require(len(records) == 1, 'Missing or ambiguous Docker archive reference: ' + reference)
        record = records[0]
        config_bytes = self.read(record['Config'])
        config_digest = digest_bytes(config_bytes)
        config = json.loads(config_bytes)
        require(config.get('os', '') + '/' + config.get('architecture', '') == platform, 'Archive platform mismatch')
        diff_ids = config.get('rootfs', {}).get('diff_ids')
        layers = record.get('Layers')
        require(isinstance(diff_ids, list) and all(DIGEST.fullmatch(str(d)) for d in diff_ids)
                and isinstance(layers, list) and len(layers) == len(diff_ids), 'Invalid archive root filesystem')
        runtime_digests = [config_digest]
        layer_descriptors = None
        if self.index is not None:
            candidates = []
            for descriptor in self.index['manifests']:
                annotations = descriptor.get('annotations', {})
                name = annotations.get('io.containerd.image.name', '')
                if name and normalized_reference(name) == normalized_reference(reference):
                    candidates.append(descriptor)
            require(len(candidates) == 1, 'Missing or ambiguous named OCI descriptor: ' + reference)
            root = candidates[0]
            selected, payload = self.platform_manifest(root, platform)
            config_descriptor = payload.get('config')
            self.check_descriptor(config_descriptor)
            require(config_descriptor['digest'] == config_digest, 'OCI config differs from Docker save config')
            layer_descriptors = payload.get('layers')
            require(isinstance(layer_descriptors, list) and len(layer_descriptors) == len(layers), 'OCI layer count mismatch')
            runtime_digests += [root['digest'], selected['digest']]
        for index, name in enumerate(layers):
            member = self.member(name)
            compressed = False
            if layer_descriptors is not None:
                descriptor = layer_descriptors[index]
                require(descriptor.get('mediaType') in LAYER_TYPES, 'Unsupported OCI layer encoding')
                require(self.check_descriptor(descriptor) == name, 'Docker and OCI layer paths differ')
                compressed = descriptor['mediaType'].endswith(('+gzip', '.gzip'))
            with self.tar.extractfile(member) as stream:
                if compressed:
                    with gzip.GzipFile(fileobj=stream) as expanded:
                        actual = digest_stream(expanded)
                else:
                    actual = digest_stream(stream)
            require(actual == diff_ids[index], 'Archive layer differs from config root filesystem')
        return {'config_digest': config_digest, 'runtime_digests': sorted(set(runtime_digests)), 'diff_ids': diff_ids}


def archive_identities(path, images, platform):
    with ImageArchive(path) as archive:
        return {image['id']: archive.identity(image['reference'], platform) for image in images}


def check_loaded_identity(inspected, identity, platform):
    require(inspected.get('Id') in identity['runtime_digests'], 'Loaded image ID mismatch')
    require(inspected.get('Os', '') + '/' + inspected.get('Architecture', '') == platform, 'Loaded image platform mismatch')
    require(inspected.get('RootFS', {}).get('Layers') == identity['diff_ids'], 'Loaded image root filesystem mismatch')
    descriptor = inspected.get('Descriptor')
    if descriptor is not None:
        require(descriptor.get('digest') in identity['runtime_digests']
                and descriptor.get('digest') != identity['config_digest'],
                'Loaded descriptor is not proven by the archive')


def merge_archives(original_path, storage_path, images, storage_reference, platform, output):
    """Copy only selected reachable bytes; no docker load, tag, build or extraction."""
    with ImageArchive(original_path) as original, ImageArchive(storage_path) as storage:
        records, descriptors, files = [], [], {}
        identities = {}

        def add_file(archive, name):
            member = archive.member(name)
            if name in files:
                # Blob names are content-addressed and checked via descriptors.
                require(files[name][1].size == member.size, 'Conflicting shared blob')
            else:
                files[name] = archive, member

        def reachable(archive, descriptor, depth=0):
            require(depth <= 6, 'OCI graph nesting exceeds limit')
            name = archive.check_descriptor(descriptor)
            add_file(archive, name)
            media = descriptor.get('mediaType')
            if media in INDEX_TYPES | MANIFEST_TYPES:
                payload = archive.json(name)
                children = payload.get('manifests') if media in INDEX_TYPES else [payload['config'], *payload['layers']]
                require(isinstance(children, list), 'Invalid OCI graph')
                for child in children:
                    reachable(archive, child, depth + 1)

        for image in images:
            is_storage = image['id'] == 'object-storage'
            archive = storage if is_storage else original
            reference = storage_reference if is_storage else image['reference']
            identity = archive.identity(reference, platform)
            identities[image['id']] = identity
            require(archive.index is not None, 'Reissue requires named OCI descriptors')
            record = next(r for r in archive.records if reference in (r.get('RepoTags') or []))
            records.append(record)
            root = next(d for d in archive.index['manifests']
                        if normalized_reference(d.get('annotations', {}).get('io.containerd.image.name', ''))
                        == normalized_reference(reference))
            descriptors.append(root)
            reachable(archive, root)
            add_file(archive, record['Config'])
            for name in record['Layers']:
                add_file(archive, name)

        def add_json(target, name, payload):
            data = json.dumps(payload, separators=(',', ':')).encode()
            member = tarfile.TarInfo(name)
            member.mode, member.size = 0o644, len(data)
            target.addfile(member, io.BytesIO(data))

        with Path(output).open('xb') as stream, tarfile.open(fileobj=stream, mode='w') as target:
            for name, (archive, member) in sorted(files.items()):
                with archive.tar.extractfile(member) as content:
                    target.addfile(member, content)
            add_json(target, 'manifest.json', records)
            add_json(target, 'index.json', {'schemaVersion': 2,
                     'mediaType': 'application/vnd.oci.image.index.v1+json', 'manifests': descriptors})
            add_json(target, 'oci-layout', {'imageLayoutVersion': '1.0.0'})
    return identities
