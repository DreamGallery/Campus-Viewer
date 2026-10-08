"""Build game music FLAC, jackets and synchronized lyrics; atomically publish the library."""
import argparse
import gc
import json
from pathlib import Path
import re
import shutil
import os
import subprocess
import tempfile
from .audio_extract import encode_flac, file_digest, wav_metadata
import yaml
from .audio_download import download_one
from .io import atomic_write
from .web_assets import decode_header, extract_one
from .unity import configure_unity

DEFAULT_IDS = ['music-char-' + cid + '-001' for cid in ('hski', 'ttmr', 'fktn', 'shro', 'jsna', 'atbm')]


def timed_lyrics(rows, start=0, clip_in=0, scale=1):
    if scale <= 0:
        raise ValueError('Invalid subtitle time scale')
    result = []
    for row in rows:
        text = re.sub(r'<[^>]+>', '', row.get('text', '')).strip()
        begin = start + (float(row['from']) - clip_in) / scale
        end = start + (float(row['to']) - clip_in) / scale
        if text and end > begin and end > 0:
            result.append({'start': round(max(0, begin), 3), 'end': round(end, 3), 'text': text})
    return sorted(result, key=lambda line: line['start'])


def extract_lyrics(path, name, song):
    import UnityPy
    configure_unity()
    env = UnityPy.load(decode_header(path.read_bytes(), name))
    files = {}
    for obj in env.objects:
        if obj.type.name == 'MonoBehaviour':
            try:
                files.setdefault(obj.assets_file.name, {})[obj.path_id] = obj.read_typetree()
            except (ValueError, TypeError):
                continue
    expected = 'srt_live_' + song
    subtitle = next(((objects, ident, data) for objects in files.values() for ident, data in objects.items()
                     if data.get('m_Name') == expected and isinstance(data.get('subtitles'), list)), None)
    if not subtitle:
        return []
    objects, ident, data = subtitle
    assets = {key for key, value in objects.items()
              if value.get('behaviour', {}).get('subtitle', {}).get('m_PathID') == ident}
    transforms = {(float(clip.get('m_Start', 0)), float(clip.get('m_ClipIn', 0)), float(clip.get('m_TimeScale', 1)))
                  for obj in objects.values() for clip in obj.get('m_Clips', [])
                  if clip.get('m_Asset', {}).get('m_PathID') in assets}
    if len(transforms) > 1:
        raise ValueError('Ambiguous subtitle timeline')
    return timed_lyrics(data['subtitles'], *next(iter(transforms), (0, 0, 1)))


def select_music(rows, resources, ids=None, scope='vocal'):
    selected = []
    requested = set(ids or [])
    for row in rows:
        if ids and row['id'] not in requested:
            continue
        asset = row.get('gameVersionAssetId', '')
        if not ids and scope == 'vocal' and (row['id'].startswith('music-bgm-') or asset.endswith('-inst')):
            continue
        # ACB may contain only a short prefetch segment; AWB holds the complete song.
        if asset + '.awb' in resources:
            selected.append(row)
    if ids and requested != {r['id'] for r in selected}:
        raise ValueError('Requested songs are missing complete AWB resources')
    return selected


def publish_file(source, output, suffix=None):
    sha = file_digest(source)
    name = source.stem + '-' + sha[:16] + (suffix or source.suffix)
    target = output / name
    if not target.is_file() or file_digest(target) != sha:
        temporary = output / ('.' + name + '.tmp')
        shutil.copyfile(source, temporary)
        temporary.chmod(0o644)
        os.replace(temporary, target)
    return name


def decode_song(source, acb, output, cache, decoder, decoder_hash, ffmpeg=None):
    fingerprint = {'awb': file_digest(source), 'acb': file_digest(acb) if acb else None,
                   'decoder': decoder_hash, 'pipeline': 1}
    marker = cache / (source.stem + '.decoded.json')
    if marker.exists():
        previous = json.loads(marker.read_text())
        target = output / previous['file']
        if (previous['source'] == fingerprint and target.is_file()
                and file_digest(target) == previous['sha256']):
            return previous
    with tempfile.TemporaryDirectory(prefix='music-', dir=cache) as folder:
        wav = Path(folder) / (source.stem + '.wav')
        result = subprocess.run([str(decoder), '-I', '-i', '-o', str(wav), str(source)],
                                check=True, capture_output=True, text=True, timeout=600)
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        if len(rows) != 1 or rows[0].get('streamInfo', {}).get('total', 1) != 1:
            raise ValueError('Expected one complete music stream')
        info = wav_metadata(wav)
        if info['sample_count'] != rows[0]['playSamples'] or info['sample_rate'] != rows[0]['sampleRate']:
            raise ValueError('Music PCM metadata mismatch')
        if ffmpeg:  # Optional local tool; Docker uses flac --verify below.
            flac = wav.with_suffix('.flac')
            subprocess.run([str(ffmpeg), '-v', 'error', '-y', '-i', str(wav), '-map_metadata', '-1',
                            '-c:a', 'flac', '-compression_level', '8', str(flac)], check=True, timeout=600)
            def pcm_hash(path):
                return subprocess.check_output([str(ffmpeg), '-v', 'error', '-i', str(path),
                    '-c:a', 'pcm_s16le', '-f', 'hash', '-hash', 'sha256', '-'], timeout=600)
            if pcm_hash(wav) != pcm_hash(flac):
                raise ValueError('FLAC PCM verification failed')
        else:
            flac = encode_flac(wav)
        filename = publish_file(flac, output)
        record = {'source': fingerprint, 'file': filename, 'sha256': file_digest(flac),
                  'encoding': rows[0].get('encoding'), 'format': 'flac', 'compression_level': 8,
                  'duration': info['sample_count'] / info['sample_rate'], **info}
        atomic_write(marker, record)
        return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--masterdata', required=True, type=Path)
    p.add_argument('--manifest', required=True, type=Path)
    p.add_argument('--output', type=Path, default=Path('data/music'))
    p.add_argument('--cache', type=Path, default=Path('data/music-source'))
    p.add_argument('--ids', nargs='+')
    p.add_argument('--scope', choices=['vocal', 'all'], default='vocal')
    p.add_argument('--decoder', type=Path, default=Path('/usr/local/bin/vgmstream-cli'))
    p.add_argument('--ffmpeg', type=Path, help='Optional local FLAC encoder; Docker uses flac -8 --verify')
    args = p.parse_args()
    manifest = json.loads(args.manifest.read_text())
    resources = {r['name']: r for r in manifest['resourceList'] if r.get('state') != 4}
    bundles = {r['name']: r for r in manifest['assetBundleList'] if r.get('state') != 4}
    music = yaml.safe_load((args.masterdata/'Music.yaml').read_text())
    characters = {r['id']: r for r in yaml.safe_load((args.masterdata/'Character.yaml').read_text())}
    selected = select_music(music, resources, args.ids, args.scope)
    if not selected:
        raise ValueError('No available songs; refusing to replace existing library')
    configure_unity()
    args.output.mkdir(parents=True, exist_ok=True)
    args.cache.mkdir(parents=True, exist_ok=True)
    decoder_hash = file_digest(args.decoder)
    def download(row):
        result = download_one(row, manifest['urlFormat'], args.cache)
        if result['status'] == 'failed':
            raise RuntimeError('Music resource download failed')
        return args.cache / row['name']
    tracks = []
    for number, row in enumerate(selected, 1):
        ident, asset = row['id'], row['gameVersionAssetId']
        print(f'Music [{number}/{len(selected)}]: {ident}', flush=True)
        awb = download(resources[asset+'.awb'])
        acb = download(resources[asset+'.acb']) if asset+'.acb' in resources else None
        decoded = decode_song(awb, acb, args.output, args.cache, args.decoder, decoder_hash, args.ffmpeg)
        match = re.fullmatch(r'sud_music_general_(.+)-([a-z0-9]+)_game(?:-inst)?', asset)
        song, cid = match.groups() if match else ('', '')
        character = characters.get(cid)
        artist = character['lastName']+' '+character['firstName'] if character else '学園アイドルマスター'
        jacket = 'img_general_music_jacket_' + row['jacketAssetId']
        if jacket+'.png' in resources:
            cover = download(resources[jacket+'.png'])
            cover_name = '/music/'+publish_file(cover, args.output)
        elif jacket in bundles:
            result = extract_one(bundles[jacket], manifest['urlFormat'], args.cache, args.cache/'covers')
            cover = args.cache/'covers'/Path(result['path']).name
            cover_name = '/music/'+publish_file(cover, args.output)
        else:
            cover_name = '/favicon.svg'
        timeline_name = 'tln_live_' + song
        cache_key = bundles[timeline_name]['md5'] if timeline_name in bundles and not asset.endswith('-inst') else None
        cached = args.cache/(timeline_name+'.lyrics.json')
        previous = json.loads(cached.read_text()) if cached.exists() else {}
        if cache_key and previous.get('source_md5') == cache_key and previous.get('parser_version') == 2:
            lyrics = previous['lines']
        elif cache_key:
            lyrics = extract_lyrics(download(bundles[timeline_name]), timeline_name, song)
            atomic_write(cached, {'source_md5': cache_key, 'parser_version': 2, 'lines': lyrics})
        else:
            lyrics = []
        # Don't attach another arrangement's timeline if it extends beyond this recording.
        if lyrics and lyrics[-1]['end'] > decoded['duration'] + 1:
            print('  Lyrics exceed recording duration; omitted', flush=True)
            lyrics = []
        tracks.append({'id': ident, 'title': row['title'], 'artist': artist, 'character_id': cid,
            'audio': '/music/'+decoded['file'], 'cover': cover_name, 'version': '游戏版本 · FLAC',
            'duration': decoded['duration'], 'format': 'flac', 'sample_rate': decoded['sample_rate'],
            'credits': {k: row.get(k) or '' for k in ('lyrics', 'composer', 'arranger')},
            'lyrics': lyrics, 'lyrics_source': timeline_name if lyrics else None})
        print(f'  FLAC verified; {len(lyrics)} timed lyric lines', flush=True)
        gc.collect()
    atomic_write(args.output/'library.json', {'schema_version': 1, 'revision': manifest['revision'], 'tracks': tracks})
    (args.output/'library.json').chmod(0o644)
    print(json.dumps({'tracks':len(tracks), 'timed_tracks':sum(bool(t['lyrics']) for t in tracks)}), flush=True)

if __name__ == '__main__':
    main()
