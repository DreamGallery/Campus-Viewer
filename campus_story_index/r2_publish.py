"""Publish immutable resources, then switch one R2 pointer. Never scan/delete foreign keys."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import time


def settings():
    required = ['CAMPUS_R2_ENDPOINT', 'CAMPUS_R2_BUCKET', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY']
    if any(not os.getenv(k) for k in required):
        raise ValueError('Missing R2 configuration: ' + ', '.join(k for k in required if not os.getenv(k)))
    prefix = os.getenv('CAMPUS_R2_PREFIX', 'campus-v1')
    if not re.fullmatch(r'[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*', prefix):
        raise ValueError('R2 prefix must be a non-empty dedicated directory')
    return os.environ['CAMPUS_R2_BUCKET'], prefix


def client():
    import boto3
    from botocore.config import Config
    settings()
    return boto3.client('s3', endpoint_url=os.environ['CAMPUS_R2_ENDPOINT'], region_name='auto',
                        config=Config(retries={'max_attempts': 5, 'mode': 'standard'},
                                      request_checksum_calculation='when_required', response_checksum_validation='when_required'))


def get_json(s3, bucket, key):
    from botocore.exceptions import ClientError
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(response['Body'].read()), response['ETag']
    except ClientError as exc:
        if str(exc.response['Error']['Code']) in ('NoSuchKey', '404'): return None, None
        raise


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()


def publish_release(root, release, s3=None):
    bucket, prefix = settings()
    s3 = s3 or client()
    previous, previous_etag = get_json(s3, bucket, prefix + '/current.json')
    stage = root / 'releases' / release
    # A lost runtime volume must not silently establish another baseline.
    local_current = root / 'current'
    if previous and not local_current.exists():
        raise RuntimeError('Remote release exists but local baseline is missing; restore the runtime volume before publishing')
    if previous and local_current.exists() and previous['release'] not in (local_current.resolve().name, release):
        raise RuntimeError('Remote and local releases differ; another updater or rollback requires reconciliation')
    versions = json.loads((stage / 'resource-versions.json').read_text())
    def upload(path, key):
        from botocore.exceptions import ClientError
        sha = key.split('/')[1] if key.startswith('media/') else digest(path)
        try:
            head = s3.head_object(Bucket=bucket, Key=prefix+'/'+key)
            if head.get('Metadata', {}).get('sha256') == sha: return
            raise RuntimeError('Immutable object collision: ' + key)
        except ClientError as exc:
            if str(exc.response['Error']['Code']) not in ('404', 'NoSuchKey', 'NotFound'): raise
        s3.upload_file(str(path), bucket, prefix+'/'+key, ExtraArgs={
            'ContentType': 'application/gzip' if key.startswith('downloads/') else (mimetypes.guess_type(path.name)[0] or 'application/octet-stream'),
            **({'ContentDisposition': 'attachment; filename="'+path.name+'"'} if key.startswith('downloads/') else {}),
            'CacheControl': 'no-store' if key.startswith('downloads/') else 'public, max-age=31536000, immutable', 'Metadata': {'sha256': sha}})
    public_base = os.getenv('CAMPUS_R2_PUBLIC_BASE_URL', '').rstrip('/')
    if public_base and not public_base.startswith('https://'): raise ValueError('Public resource base must use HTTPS')
    media = {}
    jobs = []
    for folder, url in [('audio', '/audio/'), ('web/assets/images', '/assets/images/')]:
        base = stage / folder
        if not base.exists(): continue
        for path in sorted(base.rglob('*')):
            if not path.is_file() or path.is_symlink(): continue
            key = 'media/' + digest(path) + '/' + path.name
            media[url + path.relative_to(base).as_posix()] = (public_base + '/' + prefix if public_base else '') + '/' + key
            jobs.append((path, key))
    with ThreadPoolExecutor(max_workers=max(1, min(8, int(os.getenv('CAMPUS_UPLOAD_WORKERS', '4'))))) as pool:
        list(pool.map(lambda job: upload(*job), jobs))
    def rewrite(value):
        if isinstance(value, list): return [rewrite(v) for v in value]
        if isinstance(value, dict): return {k: rewrite(v) for k, v in value.items()}
        if isinstance(value, str):
            if value in media: return media[value]
            if value.startswith('/catalog/'): return '/catalog/releases/' + release + '/' + value[len('/catalog/'):]
        return value
    # Rewriting is isolated from the local Docker release and its hard-linked cache.
    temp = root / 'cache/r2-export' / release
    temp.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((stage / 'web/catalog/manifest.json').read_text())
    catalog = stage / 'web/catalog'
    build = stage / 'web' / manifest['base_path'].lstrip('/')
    if not build.resolve().is_relative_to(catalog.resolve()): raise ValueError('Invalid catalog base_path')
    files = [catalog / 'manifest.json'] + sorted(build.rglob('*.json'))
    text_jobs = []
    for source in files:
        relative = source.relative_to(stage)
        out = temp / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rewrite(json.loads(source.read_text())), ensure_ascii=False, separators=(',', ':')))
        text_jobs.append((out, 'releases/' + release + '/' + relative.as_posix()))
    for folder, suffix in [('story', '.csv'), ('adv', '.txt')]:
        for path in sorted((stage / folder).rglob('*')):
            if path.is_file() and not path.is_symlink() and path.suffix.lower() == suffix:
                text_jobs.append((path, 'releases/' + release + '/' + path.relative_to(stage).as_posix()))
    with ThreadPoolExecutor(max_workers=max(1, min(8, int(os.getenv('CAMPUS_UPLOAD_WORKERS', '4'))))) as pool:
        list(pool.map(lambda job: upload(*job), text_jobs))
    for version in versions['versions']:
        name = version['filename']
        if not re.fullmatch(r'campus-resources-r[0-9]+-[a-f0-9]{12}\.tar\.gz', name): raise ValueError('Invalid archive filename')
        upload(root / 'downloads' / name, 'downloads/' + name)
    for name in ['resource-snapshot.json', 'resource-versions.json']:
        upload(stage / name, 'releases/' + release + '/' + name)
    pointer = {'schema_version': 1, 'release': release, 'published_at': int(time.time()), 'versions': versions}
    # Conditional publication rejects competing updaters, including the first publication.
    condition = {'IfMatch': previous_etag} if previous_etag else {'IfNoneMatch': '*'}
    s3.put_object(Bucket=bucket, Key=prefix+'/current.json', Body=json.dumps(pointer).encode(),
                  ContentType='application/json', CacheControl='no-store', **condition)
    # Only remove archives explicitly owned by the preceding release. Keep media and
    # catalog snapshots for open tabs/rollback; their garbage collection is deliberate.
    retained = {v['filename'] for v in versions['versions']}
    for version in (previous or {}).get('versions', {}).get('versions', []):
        name = version['filename']
        if name not in retained and re.fullmatch(r'campus-resources-r[0-9]+-[a-f0-9]{12}\.tar\.gz', name):
            try: s3.delete_object(Bucket=bucket, Key=prefix+'/downloads/'+name)
            except Exception: print('R2 archive cleanup deferred; publication succeeded', flush=True)
    return pointer


def main():
    parser = argparse.ArgumentParser(description='Upload an already initialized local release to R2')
    parser.add_argument('--root', type=Path, default=Path(os.getenv('CAMPUS_RUNTIME_ROOT', '/runtime')))
    args = parser.parse_args()
    import fcntl
    with (args.root / 'update.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release = (args.root / 'current').resolve(strict=True).name
        publish_release(args.root, release)
    print('R2 release published: ' + release)


if __name__ == '__main__': main()
