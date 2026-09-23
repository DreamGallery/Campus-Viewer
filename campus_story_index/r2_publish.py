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
from threading import Event, Lock, Thread


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


class UploadProgress:
    """Thread-safe counters plus a heartbeat even while a request is retrying."""
    def __init__(self, label, total):
        self.label, self.total = label, total
        self.uploaded = self.skipped = self.failed = self.bytes = 0
        self.lock = Lock()
        self.stop = Event()
        self.started = time.monotonic()

    def transferred(self, count):
        with self.lock:
            self.bytes += count

    def finish(self, status):
        with self.lock:
            setattr(self, status, getattr(self, status) + 1)

    def report(self):
        with self.lock:
            done = self.uploaded + self.skipped + self.failed
            percent = done / self.total * 100 if self.total else 100
            print(f'R2 [{self.label}] {done}/{self.total} ({percent:.1f}%) '
                  f'已上传={self.uploaded} 已跳过={self.skipped} 失败={self.failed} '
                  f'本轮传输={self.bytes / 1048576:.1f} MiB '
                  f'耗时={time.monotonic() - self.started:.0f}s', flush=True)

    def heartbeat(self):
        while not self.stop.wait(10):
            self.report()

    def __enter__(self):
        self.report()
        self.thread = Thread(target=self.heartbeat, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join()
        self.report()


def list_media(s3, bucket, prefix, namespace="media"):
    """Inventory only our immutable, content-addressed media namespace."""
    print(f'R2: 批量读取远端 {namespace} 清单', flush=True)
    result = {}
    pages = 0
    media_prefix = prefix + '/' + namespace + '/'
    for page in s3.get_paginator('list_objects_v2').paginate(
            Bucket=bucket, Prefix=media_prefix, PaginationConfig={'PageSize': 1000}):
        for item in page.get('Contents', []):
            key = item['Key']
            if key.startswith(media_prefix):
                result[key[len(prefix) + 1:]] = item['Size']
        pages += 1
        if pages == 1 or pages % 10 == 0:
            print(f'R2: 远端 {namespace} 清单 {pages} 页 / {len(result)} 个文件', flush=True)
    print(f'R2: 远端 {namespace} 清单读取完成 {pages} 页 / {len(result)} 个文件', flush=True)
    return result


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
    remote_media = list_media(s3, bucket, prefix)
    remote_media.update(list_media(s3, bucket, prefix, 'text'))
    def upload(path, key, progress):
        from botocore.exceptions import ClientError
        sha = key.split('/')[1] if key.startswith(('media/', 'text/')) else digest(path)
        if key.startswith(('media/', 'text/')) and key in remote_media:
            # The SHA-256 is part of the immutable object key, not the multipart ETag.
            if remote_media[key] != path.stat().st_size:
                raise RuntimeError('Immutable media size mismatch')
            return 'skipped'
        try:
            head = s3.head_object(Bucket=bucket, Key=prefix+'/'+key)
            if head.get('Metadata', {}).get('sha256') == sha: return 'skipped'
            raise RuntimeError('Immutable object collision: ' + key)
        except ClientError as exc:
            if str(exc.response['Error']['Code']) not in ('404', 'NoSuchKey', 'NotFound'): raise
        s3.upload_file(str(path), bucket, prefix+'/'+key, Callback=progress.transferred, ExtraArgs={
            'ContentType': 'application/gzip' if key.startswith('downloads/') else (mimetypes.guess_type(path.name)[0] or 'application/octet-stream'),
            **({'ContentDisposition': 'attachment; filename="'+path.name+'"'} if key.startswith('downloads/') else {}),
            'CacheControl': 'no-store' if key.startswith('downloads/') else 'public, max-age=31536000, immutable', 'Metadata': {'sha256': sha}})
        return 'uploaded'

    def batch(label, jobs, workers=None):
        workers = workers or max(1, min(8, int(os.getenv('CAMPUS_UPLOAD_WORKERS', '4'))))
        with UploadProgress(label, len(jobs)) as progress:
            def process(job):
                try:
                    progress.finish(upload(*job, progress))
                except Exception as exc:
                    progress.finish('failed')
                    # Do not log exception messages: SDK errors may contain credentials or URLs.
                    print(f'R2 [{label}] 文件上传失败: {type(exc).__name__}', flush=True)
                    raise
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for _ in pool.map(process, jobs):
                    pass

    print('R2: 正在扫描图片和语音并计算校验值', flush=True)
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
    batch('图片与语音', jobs)
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
    file_map = {}
    previous_map = None
    if previous:
        previous_map, _ = get_json(s3, bucket, prefix + '/releases/' + previous['release'] + '/file-map.json')
    def add_text(path, relative):
        # Reuse already-published legacy CSV/TXT on the first upgrade as well.
        old = root / 'releases' / previous['release'] / relative if previous else None
        if relative.startswith(('story/', 'adv/')) and old and old.is_file() and digest(old) == digest(path):
            old_key = (previous_map or {}).get('files', {}).get(relative) if previous_map else 'releases/' + previous['release'] + '/' + relative
            if old_key:
                file_map[relative] = old_key
                return
        key = 'text/' + digest(path) + '/' + path.name
        file_map[relative] = key
        text_jobs.append((path, key))
    for source in files:
        relative = source.relative_to(stage)
        out = temp / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rewrite(json.loads(source.read_text())), ensure_ascii=False, separators=(',', ':')))
        add_text(out, relative.as_posix())
    for folder, suffix in [('story', '.csv'), ('adv', '.txt')]:
        for path in sorted((stage / folder).rglob('*')):
            if path.is_file() and not path.is_symlink() and path.suffix.lower() == suffix:
                add_text(path, path.relative_to(stage).as_posix())
    print(f'R2: 复用上版文本 {len(file_map) - len(text_jobs)} 个，其余按内容校验', flush=True)
    batch('文本与索引', list(dict.fromkeys(text_jobs)))
    map_path = temp / 'file-map.json'
    map_path.write_text(json.dumps({'schema_version': 1, 'files': file_map}, ensure_ascii=False, separators=(',', ':')))
    batch('文件映射', [(map_path, 'releases/' + release + '/file-map.json')], workers=1)
    archive_jobs = []
    for version in versions['versions']:
        name = version['filename']
        if not re.fullmatch(r'campus-resources-r[0-9]+-[a-f0-9]{12}\.tar\.gz', name): raise ValueError('Invalid archive filename')
        archive_jobs.append((root / 'downloads' / name, 'downloads/' + name))
    batch('增量资源包', archive_jobs, workers=1)
    metadata_jobs = []
    for name in ['resource-snapshot.json', 'resource-versions.json']:
        metadata_jobs.append((stage / name, 'releases/' + release + '/' + name))
    batch('版本信息', metadata_jobs, workers=1)
    print('R2: 正在切换已发布版本', flush=True)
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
    print(f'R2: 发布完成 {release}', flush=True)
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
