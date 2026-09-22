"""Toolkit API-compatible game update output, with verified downloads and resumable work."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from .audio_download import download_one
from .io import atomic_write
from .web_assets import decode_header

ASSET = {'crw': 'sticker', 'eff': 'effect', 'env': 'environment', 'fbx': 'model/fbx_model',
         'fgd': 'image/fgd', 'img': 'image', 'mdl': 'model', 'mef': 'sticker/face',
         'mot': 'script/motion', 'scl': 'script/cinema', 'shader': 'shader', 'sky': 'sky',
         'sud': 'sound', 'tln': 'script/live', 'ttn': 'script/adventure'}
RESOURCE = {'adv': 'adventure', 'img': 'image', 'mov': 'movie', 'sud': 'sound'}


def safe_name(name):
    # The game manifest contains U+2010 in short‐circuit. Preserve the exact name;
    # normalizing it would break remote resource identity and incremental matching.
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.\-\u2010]+', name) or name in ('.', '..'):
        raise ValueError('Unsafe resource filename')
    return name


def snapshot(manifest):
    return {kind + '/' + safe_name(row['name']): {'name': row['name'], 'md5': row['md5'], 'size': row['size']}
            for kind in ('assetBundleList', 'resourceList') for row in manifest[kind] if row.get('state') != 4}


def stretch_size(name):
    if (name.startswith('img_general_cidol-') and name.endswith('-full')) or name.startswith('img_adv_still_'):
        return (1440, 2560)
    if name.startswith('img_general_csprt-') and name.endswith('_full'):
        return (2560, 1440)
    if name.startswith('img_general_comic_'):
        return (1024, 768)
    return None


def classify(kind, name):
    if kind == 'assetBundleList' and 'shader' in name:
        return 'shader'
    mapping = ASSET if kind == 'assetBundleList' else RESOURCE
    return next((mapping[part] for part in name.split('_')[:2] if part in mapping), 'other')


def extract_item(kind, item, raw, dest):
    import UnityPy
    from PIL import Image
    name = safe_name(item['name'])
    prefix = 'assetbundle' if kind == 'assetBundleList' else 'resource'
    target = dest / prefix / classify(kind, name) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if kind == 'resourceList':
        shutil.copyfile(raw, target)
        return
    payload = decode_header(raw.read_bytes(), name)
    target.write_bytes(payload)
    env = UnityPy.load(payload)
    for obj in env.objects:
        if obj.type.name != 'Texture2D':
            continue
        data = obj.read()
        texture_name = getattr(data, 'm_Name', None) or getattr(data, 'name', '')
        if not texture_name.startswith(('env', 'img')):
            continue
        safe_name(texture_name)
        image = data.image
        path = dest / 'image/Texture2D' / (texture_name + '.png')
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, 'PNG')
        size = stretch_size(name) if texture_name == name else None
        if size:
            stretched = dest / 'stretch' / (name + '.png')
            stretched.parent.mkdir(parents=True, exist_ok=True)
            image.resize(size, Image.Resampling.LANCZOS).save(stretched, 'PNG')


def build_package(root, manifest, before, full=False):
    import UnityPy
    UnityPy.config.FALLBACK_UNITY_VERSION = '2022.3.21f1'
    current = snapshot(manifest)
    changes = [(kind, row) for kind in ('assetBundleList', 'resourceList') for row in manifest[kind]
               if row.get('state') != 4 and (full or before.get(kind + '/' + row['name']) != current[kind + '/' + row['name']])]
    # A recipe version invalidates partially processed caches when conversion rules change.
    identity = hashlib.sha256(json.dumps([2, current, before, full], sort_keys=True).encode()).hexdigest()
    work = root / 'cache/game-packages' / identity
    dest = work / 'output'; dest.mkdir(parents=True, exist_ok=True)
    workers = max(1, min(8, int(os.getenv('CAMPUS_DOWNLOAD_WORKERS', '4'))))
    def process(pair):
        kind, item = pair
        raw_dir = work / 'raw' / kind
        result = download_one(item, manifest['urlFormat'], raw_dir)
        if result['status'] == 'failed':
            raise RuntimeError('Game resource download failed: ' + item['name'])
        # Each item is isolated for deterministic merges and safe retries after interruption.
        item_dir = work / 'processed' / kind / safe_name(item['name'])
        marker = item_dir / '.complete'
        if not marker.exists():
            if item_dir.exists(): shutil.rmtree(item_dir)
            item_dir.mkdir(parents=True)
            extract_item(kind, item, raw_dir / item['name'], item_dir)
            marker.write_text('ok')
        return item_dir
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process, pair): pair for pair in changes}
        completed = 0
        for future in as_completed(futures):
            future.result()
            completed += 1
            if completed % 100 == 0 or completed == len(changes):
                print(f'Game package: {completed}/{len(changes)}', flush=True)
    # Merge in manifest order like the source layout. Keep unscaled originals alongside stretch/.
    for kind, item in changes:
        item_dir = work / 'processed' / kind / item['name']
        for file in sorted(item_dir.rglob('*')):
            if not file.is_file() or file.name == '.complete': continue
            target = dest / file.relative_to(item_dir); target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists(): target.unlink()
            os.link(file, target)
    atomic_write(dest / 'package.json', {'revision': manifest['revision'], 'kind': 'full' if full else 'incremental',
                 'files': len(changes), 'removed': sorted(set(before) - set(current)),
                 'resources': {kind + '/' + row['name']: current[kind + '/' + row['name']] for kind, row in changes}})
    return dest
