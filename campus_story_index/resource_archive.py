"""Publish only complete downloadable snapshots; retain five distinct revisions."""
import hashlib
import json
import os
import shutil
from pathlib import Path
import tarfile
import time
import uuid

from .io import atomic_write
from .game_package import build_package, snapshot



def portable_archive_member(member):
    """Do not export container/NAS permissions, owners or extended metadata."""
    member.mode = 0o755 if member.isdir() else 0o644
    member.uid = member.gid = 0
    member.uname = member.gname = ''
    # PAX ACL/owner/mode extensions can override the normalized tar header.
    # Retain only portable path, size and timestamp fields (including long names).
    member.pax_headers = {key: value for key, value in member.pax_headers.items()
                          if key in {'path', 'linkpath', 'size', 'mtime'}}
    return member


def prepare_archive(root, release, manifest):
    revision = str(manifest["revision"])
    if not revision.isdigit():
        raise ValueError('Expected numeric game resource revision')
    folder = root / 'downloads'
    folder.mkdir(exist_ok=True)
    previous = root / 'current/resource-versions.json'
    versions = json.loads(previous.read_text())['versions'] if previous.exists() else []
    existing = next((v for v in versions if v['revision'] == revision and (folder / v['filename']).is_file()), None)
    baseline_path = root / 'current/resource-snapshot.json'
    baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else None
    atomic_write(release / 'resource-snapshot.json', {'revision': revision, 'resources': snapshot(manifest)})
    if baseline is None or baseline['revision'] == revision:
        atomic_write(release / 'resource-versions.json', {'revision': revision, 'versions': versions, 'baseline_only': not versions})
        (release / 'resource-versions.json').chmod(0o644)
        return versions
    if existing is None:
        package = build_package(root, manifest, baseline['resources'])
        filename = f'campus-resources-r{revision}-{uuid.uuid4().hex[:12]}.tar.gz'
        partial = folder / ('.' + filename)
        try:
            with tarfile.open(partial, 'w:gz', compresslevel=1, dereference=True) as archive:
                # Only processed game outputs; never website data, config, repository or credentials.
                for file in sorted(package.iterdir()):
                    archive.add(file, arcname=file.name, filter=portable_archive_member)
            checksum = hashlib.sha256()
            with partial.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    checksum.update(chunk)
            partial.chmod(0o644)
            os.replace(partial, folder / filename)
            if package.parent.parent == root / 'cache/game-packages':
                shutil.rmtree(package.parent, ignore_errors=True)
        finally:
            partial.unlink(missing_ok=True)
        existing = {'revision': revision, 'from_revision': baseline['revision'], 'kind': 'incremental', 'filename': filename,
                    'url': '/api/resources/download/' + filename,
                    'bytes': (folder / filename).stat().st_size,
                    'sha256': checksum.hexdigest(), 'created_at': int(time.time())}
    versions = [existing] + [v for v in versions if v['revision'] != revision]
    versions = versions[:5]
    atomic_write(release / 'resource-versions.json', {'revision': revision, 'versions': versions})
    (release / 'resource-versions.json').chmod(0o644)
    return versions


def prune_archives(root, versions):
    keep = {v['filename'] for v in versions}
    for file in (root / 'downloads').glob('campus-resources-r*.tar.gz'):
        if file.name not in keep:
            try:
                file.unlink()
            except OSError as exc:
                print(f'Archive cleanup postponed: {type(exc).__name__}', flush=True)
