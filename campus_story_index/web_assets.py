"""Download and extract only images referenced by the web catalog.
Header deobfuscation adapted from the user's HatsuboshiWebsite/src/decrypt.py.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import os
import tempfile
from .audio_download import download_one
from .io import atomic_write
from .pending_text import filename_hints


# Verified notice-list artwork for events whose ordinary large banner is absent.
EVENT_COVER_ALTERNATIVES = {
    'img_general_event_anniv-01_anniv-01-story-banner':
        'img_general_event_anniv-01_anniv-01-story-header',
    'img_general_event_aprilfool_aprilfool-2025-01-story-banner':
        'img_general_event_aprilfool_aprilfool-2025-01-story-header',
    'img_general_event_story_event-story-005-story-banner':
        'img_notice_notice-list_event_story_event-story-005-banner',
}


def decode_header(payload, name):
    if payload.startswith(b'Unity'):
        return payload
    if not name or len(payload) < 256:
        raise ValueError('Invalid bundle header')
    mask = bytearray(len(name) * 2)
    for i, char in enumerate(name.encode('ascii')):
        mask[i * 2] = char
        mask[len(mask) - 1 - i * 2] = ~char & 255
    checksum = 0x9b
    for value in mask:
        checksum = (((checksum & 1) << 7) | (checksum >> 1)) ^ value
    mask = bytes(value ^ checksum for value in mask)
    result = bytearray(payload)
    for i in range(256):
        result[i] ^= mask[i % len(mask)]
    if not result.startswith(b'Unity'):
        raise ValueError('Not a Unity bundle')
    return bytes(result)


def image_requests(catalog):
    names = set()
    stamp_characters = {c['id'] for c in catalog['characters'] if c['is_playable']}
    stamp_characters.update(cid for g in catalog['groups'] if g['kind'] == 'support_card'
                            for cid in g.get('character_ids', []))
    for ident in stamp_characters:
        names.update(f"img_general_stamp_{ident}-{stage:02}" for stage in (1, 2))
    for c in catalog['characters']:
        names.add(f"img_chr_{c['id']}_00-thumb-circle")
        if c['is_playable']:
            names.update([f"img_chr_{c['id']}_00-full", f"img_chr_{c['id']}_00-thumb-circle",
                          f"img_general_sign_{c['id']}_00"])
    for g in catalog['groups']:
        name = g['image_asset_id']
        if not name:
            continue
        if g['kind'] == 'idol_card':
            names.update(f'img_general_{name}_{stage}-full' for stage in (0, 1))
            continue
        elif g['kind'] == 'support_card':
            name = f'img_general_{name}_full'
        if name.startswith('img_'):
            names.add(name)
            if name in EVENT_COVER_ALTERNATIVES:
                names.add(EVENT_COVER_ALTERNATIVES[name])
            if name.endswith('-story-banner'):
                names.add(name.removesuffix('-story-banner') + '-banner')
    for record in catalog.get('source_records', []):
        if record['id'].startswith('MainStoryChapter:'):
            asset_id = record['data'].get('storyAssetId')
            if asset_id:
                names.add(f'img_general_commu_chapter-thumb_{asset_id}')
    for script in catalog.get("scripts", []):
        hints = filename_hints(script["id"], [])
        names.update(name for name, _ in hints["images"])
    return sorted(names)


def is_event_banner(name):
    return bool(re.fullmatch(r"img_general.*event.*(?<!story)(?<!reward)(?<!rev)-banner", name))


def display_size(name, source_size=None):
    # HatsuboshiToolkit origin/main src/image_process.py image_scale.
    if name.startswith('img_general_cidol-') and name.endswith('-full'):
        return (1440, 2560)
    if name.startswith('img_general_csprt-') and name.endswith('_full'):
        return (2560, 1440)
    if is_event_banner(name) and source_size:
        w, h = source_size
        return (w, int(w / 3 + 0.5)) if w / h > 3 else (int(h * 3 + 0.5), h)
    return None


def extract_one(item, url_format, cache, output):
    import UnityPy
    name = item['name']
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('Unsafe asset name')
    result = download_one(item, url_format, cache)
    if result['status'] == 'failed':
        return result
    # Content-addressed output: updates cannot replace assets used by old indexes.
    recipe = "banner-3to1-v1" if is_event_banner(name) else "stretch-v2" if display_size(name) else "trim-v1"
    target = output / f"{name}.{item['md5']}.{recipe}.webp"
    if target.exists():
        target.chmod(0o644)
        from PIL import Image
        with Image.open(target) as image:
            image.load()
            width, height = image.size
        return {'name': name, 'status': 'cached', 'path': f'images/{target.name}',
                'width': width, 'height': height, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    env = UnityPy.load(decode_header((cache / name).read_bytes(), name))
    candidates = []
    for obj in env.objects:
        if obj.type.name in ('Texture2D', 'Sprite'):
            data = obj.read()
            if data.m_Name == name:
                candidates.append(data)
    if not candidates:
        raise ValueError('Expected named image missing')
    # Prefer a Sprite's cropped image where both Sprite and Texture2D exist.
    image = candidates[-1].image
    size = display_size(name, image.size)
    if size:
        from PIL import Image
        image = image.resize(size, Image.Resampling.LANCZOS)
    elif image.mode == 'RGBA':
        bounds = image.getchannel('A').getbbox()
        if bounds:
            image = image.crop(bounds)
    if not size:
        image.thumbnail((1600, 2000))
    output.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=output, suffix='.webp')
    os.close(fd)
    try:
        image.save(temporary, 'WEBP', quality=90, method=4)
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {'name': name, 'status': 'extracted', 'path': f'images/{target.name}',
            'width': image.width, 'height': image.height,
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--catalog', type=Path, default=Path('generated/story-index.json'))
    p.add_argument('--manifest', type=Path, default=Path('data/audio/OctoManifest.json'))
    p.add_argument('--output', type=Path, default=Path('data/web/assets'))
    p.add_argument('--cache', type=Path, default=Path('data/images/bundles'))
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--unity-version', default='2022.3.21f1', help='Fallback version from HatsuboshiWebsite config')
    args = p.parse_args()
    import UnityPy
    UnityPy.config.FALLBACK_UNITY_VERSION = args.unity_version
    if not 1 <= args.workers <= 8:
        p.error('workers must be 1..8')
    manifest = json.loads(args.manifest.read_text())
    assets = {r['name']: r for r in manifest['assetBundleList'] if r.get('state') != 4}
    names = image_requests(json.loads(args.catalog.read_text()))
    results = [{'name': name, 'status': 'not_in_manifest'} for name in names if name not in assets]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(extract_one, assets[name], manifest['urlFormat'], args.cache,
                               args.output / 'images'): name for name in names if name in assets}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({'name': futures[future], 'status': 'failed', 'error': type(exc).__name__ + ': ' + str(exc)[:160]})
            if len(results) % 20 == 0:
                print(f'{len(results)}/{len(names)} images', flush=True)
    atomic_write(args.output / 'manifest.json', {'revision': manifest['revision'],
                 'images': sorted(results, key=lambda r: r['name'])})
    (args.output / 'manifest.json').chmod(0o644)
    from collections import Counter
    print(dict(Counter(r['status'] for r in results)), flush=True)
    return int(any(r['status'] == 'failed' for r in results))

if __name__ == '__main__':
    raise SystemExit(main())
