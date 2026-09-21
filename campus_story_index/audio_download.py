"""Download only referenced voice banks. No uploads, source deletion, or shell interpolation."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import urljoin

import requests
from .io import atomic_write, digest


def fetch_manifest(config_path=None, config_repo=None, config_ref='resource'):
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    from google.protobuf.json_format import MessageToDict
    from .vendor.octodb_pb2 import Database
    config = configparser.ConfigParser(comment_prefixes='/', allow_no_value=True)
    config.optionxform = str
    if config_repo:
        text = subprocess.run(['git', '-C', str(config_repo), 'show', f'{config_ref}:config.ini'],
                              capture_output=True, text=True, check=True).stdout
    else:
        text = Path(config_path).read_text()
    config.read_string(text)
    values = config['Octo settings']
    url = urljoin(values['URL'], f"v2/pub/a/{values['APP_ID']}/v/{values['VERSION']}/list/0")
    headers = {'Accept': f"application/x-protobuf,x-octo-app/{values['APP_ID']}",
               'X-OCTO-KEY': values['CLIENT_SECRET_KEY']}
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=(15, 60))
            if response.status_code != 200:
                raise ValueError(f'Manifest HTTP status {response.status_code}')
            payload = response.content
            key = hashlib.sha256(values['A'].encode()).digest()
            decoded = unpad(AES.new(key, AES.MODE_CBC, payload[:16]).decrypt(payload[16:]), 16)
            result = MessageToDict(Database.FromString(decoded), preserving_proto_field_name=True,
                                   use_integers_for_enums=True)
            if not result.get('resourceList') or not result.get('urlFormat'):
                raise ValueError('Manifest has no resource list or URL format')
            return result
        except requests.RequestException:
            if attempt == 2:
                raise ValueError('Manifest request failed after retries') from None
            time.sleep(2 ** attempt)
    raise ValueError('Manifest request failed')


def bank_for_cue(cue, bank_names):
    """Candidate bank only. Cue membership must later be checked by the decoder."""
    parts = cue.split('_')
    for length in range(len(parts), 0, -1):
        prefix = '_'.join(parts[:length])
        if prefix in bank_names:
            return prefix
    return None


def make_plan(manifest, adv_root, catalog):
    resources = {r['name']: r for r in manifest['resourceList'] if r.get('state') != 4}
    banks = {Path(n).stem for n in resources if n.endswith('.acb')}
    cues = set()
    script_hashes = {}
    for path in sorted(Path(adv_root).rglob('adv_*.txt')):
        content = path.read_bytes()
        script_hashes[str(path.relative_to(adv_root))] = digest(content)
        for line in content.decode('utf-8-sig').splitlines():
            if line.startswith('[voice '):
                match = re.search(r' voice=([^\s\]]+)', line)
                if match and match[1].startswith('sud_'):
                    cues.add(match[1])
    for entry in catalog['entries']:
        cues.update(v['asset_id'] for v in entry['voice_bindings'] if v['asset_id'].startswith('sud_'))
    selected = set()
    cue_banks = {}
    unmatched = []
    for cue in sorted(cues):
        bank = bank_for_cue(cue, banks)
        if bank:
            cue_banks[cue] = bank
            selected.add(bank + '.acb')
            if bank + '.awb' in resources:
                selected.add(bank + '.awb')
        else:
            unmatched.append(cue)
    rows = [resources[n] for n in sorted(selected)]
    for row in rows:
        if Path(row['name']).name != row['name'] or '\\' in row['name'] or '..' in row['name']:
            raise ValueError('Unsafe resource filename')
        if not re.fullmatch(r'[0-9a-fA-F]{32}', row.get('md5', '')):
            raise ValueError('Resource lacks valid MD5')
    return {'schema_version': '1.0.0', 'manifest_revision': manifest['revision'],
            'resource_count': len(rows), 'total_bytes': sum(r['size'] for r in rows),
            'cue_count': len(cues), 'cue_banks': cue_banks, 'unresolved_cues': unmatched,
            'adv_hashes': script_hashes, 'resources': rows}


def valid_download(path, item):
    if not path.is_file() or path.stat().st_size != item['size']:
        return False
    checksum = hashlib.md5()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest() == item['md5'].lower()


def download_one(item, url_format, output, retries=3):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    target = output / item['name']
    if valid_download(target, item):
        return {'name': item['name'], 'status': 'cached', 'bytes': item['size']}
    # Non-sensitive error descriptions; never persist request URLs, headers or credentials.
    error = 'download_failed'
    for attempt in range(retries):
        temporary = None
        try:
            url = url_format.replace('{o}', item['objectName'])
            with requests.get(url, stream=True, timeout=(15, 60)) as response:
                if response.status_code != 200:
                    raise ValueError(f'http_{response.status_code}')
                with tempfile.NamedTemporaryFile(dir=output, prefix='.' + item['name'], delete=False) as file:
                    temporary = Path(file.name)
                    for chunk in response.iter_content(1024 * 1024):
                        file.write(chunk)
            if not valid_download(temporary, item):
                raise ValueError('checksum_or_size_mismatch')
            os.replace(temporary, target)
            return {'name': item['name'], 'status': 'downloaded', 'bytes': item['size']}
        except requests.RequestException:
            error = 'network_error'
        except ValueError as exc:
            error = str(exc)
        except OSError:
            error = 'filesystem_error'
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
        if attempt + 1 < retries:
            time.sleep(2 ** attempt)
    return {'name': item['name'], 'status': 'failed', 'error': error}


def download_plan(plan, manifest, directory, workers=8):
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(download_one, row, manifest['urlFormat'], Path(directory) / 'banks')
                   for row in plan['resources']]
        for future in as_completed(futures):
            results.append(future.result())
            if len(results) % 100 == 0 or len(results) == len(futures):
                print(json.dumps({'completed': len(results), 'total': len(futures),
                                  'statuses': dict(Counter(r['status'] for r in results))}), flush=True)
                atomic_write(Path(directory) / 'download-progress.json', {
                    'manifest_revision': plan['manifest_revision'],
                    'results': sorted(results, key=lambda r: r['name'])})
    report = {'manifest_revision': plan['manifest_revision'],
              'results': sorted(results, key=lambda r: r['name'])}
    atomic_write(Path(directory) / 'download-report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description='Download source-verified story voice banks')
    parser.add_argument('--manifest', default='data/audio/OctoManifest.json')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--config-repo', type=Path)
    parser.add_argument('--config-ref', default='resource')
    parser.add_argument('--refresh-manifest', action='store_true')
    parser.add_argument('--adv', required=True, type=Path)
    parser.add_argument('--catalog', default='generated/story-index.json', type=Path)
    parser.add_argument('--output', default='data/audio', type=Path)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--plan-only', action='store_true')
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 16:
        parser.error('--workers must be between 1 and 16')
    if args.refresh_manifest or not Path(args.manifest).exists():
        if not (args.config or args.config_repo):
            parser.error('Manifest acquisition requires --config or --config-repo')
        manifest = fetch_manifest(args.config, args.config_repo, args.config_ref)
        atomic_write(args.manifest, manifest)
    else:
        manifest = json.loads(Path(args.manifest).read_text())
    plan = make_plan(manifest, args.adv, json.loads(args.catalog.read_text()))
    atomic_write(args.output / 'download-plan.json', plan)
    print(json.dumps({k: plan[k] for k in ['manifest_revision', 'resource_count', 'total_bytes', 'cue_count']}) ,flush=True)
    if not args.plan_only:
        report = download_plan(plan, manifest, args.output, args.workers)
        return int(any(r['status'] == 'failed' for r in report['results']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
