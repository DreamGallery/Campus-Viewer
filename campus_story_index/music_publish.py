"""Publish verified song assets first, then atomically switch an independent music index."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import mimetypes
import os
from pathlib import Path
import tempfile
import time

from .r2_publish import client, settings, get_json, digest, UploadProgress


def prepare_library(directory, prefix, public_base):
    directory = Path(directory).resolve()
    library = json.loads((directory / 'library.json').read_text())
    if library.get('schema_version') != 1 or not library.get('tracks'):
        raise ValueError('Invalid or empty music library')
    if public_base and not public_base.startswith('https://'):
        raise ValueError('Public resource base must use HTTPS')
    jobs = {}
    rewritten = copy.deepcopy(library)
    for track in rewritten['tracks']:
        if track.get('format') != 'flac' or not track['audio'].endswith('.flac'):
            raise ValueError('Music publication requires FLAC')
        for field in ('audio', 'cover'):
            url = track[field]
            if field == 'cover' and url == '/favicon.svg':
                continue
            if not url.startswith('/music/'):
                raise ValueError('Invalid local music URL')
            path = (directory / url[len('/music/'):]).resolve()
            if not path.is_relative_to(directory) or not path.is_file():
                raise ValueError('Missing or unsafe music file')
            sha = digest(path)
            key = 'media/' + sha + '/' + path.name
            jobs[key] = path
            track[field] = (public_base.rstrip('/') + '/' + prefix if public_base else '') + '/' + key
    return rewritten, jobs


def publish_music(directory, s3=None):
    bucket, prefix = settings()
    s3 = s3 or client()
    previous, etag = get_json(s3, bucket, prefix+'/music/current.json')
    library, jobs = prepare_library(directory, prefix, os.getenv('CAMPUS_R2_PUBLIC_BASE_URL', ''))
    from botocore.exceptions import ClientError
    from boto3.s3.transfer import TransferConfig
    transfer = TransferConfig(multipart_threshold=64 * 1024 * 1024, max_concurrency=2)
    def upload(key, path, progress):
        sha = key.split('/')[1]
        try:
            head = s3.head_object(Bucket=bucket, Key=prefix+'/'+key)
            if head.get('Metadata', {}).get('sha256') != sha:
                raise ValueError('Immutable music resource collision')
            progress.finish('skipped')
            return
        except ClientError as exc:
            if str(exc.response['Error']['Code']) not in ('404', 'NoSuchKey', 'NotFound'):
                raise
        s3.upload_file(str(path), bucket, prefix+'/'+key, Callback=progress.transferred, Config=transfer, ExtraArgs={
            'ContentType': 'audio/flac' if path.suffix == '.flac' else (mimetypes.guess_type(path.name)[0] or 'application/octet-stream'),
            'CacheControl': 'public, max-age=31536000, immutable', 'Metadata': {'sha256': sha}})
        progress.finish('uploaded')
    body = json.dumps(library, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    import hashlib
    library_key = 'text/'+hashlib.sha256(body).hexdigest()+'/music-library.json'
    with tempfile.TemporaryDirectory(prefix='music-publish-') as temp:
        path = Path(temp)/'music-library.json'; path.write_bytes(body)
        jobs[library_key] = path
        with UploadProgress('歌曲、封面与歌词', len(jobs)) as progress:
            def process(job):
                try:
                    upload(*job, progress)
                except Exception:
                    progress.finish('failed')
                    raise
            with ThreadPoolExecutor(max_workers=max(1,min(8,int(os.getenv('CAMPUS_UPLOAD_WORKERS','4'))))) as pool:
                for _ in pool.map(process, jobs.items()):
                    pass
    if previous and previous.get('library') == library_key:
        print('R2: 音乐索引未变化', flush=True)
        return previous
    pointer = {'schema_version': 1, 'library': library_key, 'revision': library['revision'],
               'tracks': len(library['tracks']), 'published_at': int(time.time())}
    s3.put_object(Bucket=bucket, Key=prefix+'/music/current.json', Body=json.dumps(pointer).encode(),
                  ContentType='application/json', CacheControl='no-store',
                  **({'IfMatch': etag} if etag else {'IfNoneMatch': '*'}))
    print(f'R2: 音乐索引已发布，共 {len(library["tracks"])} 首', flush=True)
    return pointer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    publish_music(args.directory)

if __name__ == '__main__':
    main()
