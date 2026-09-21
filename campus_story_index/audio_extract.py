"""ACB/AWB to verified WAVs, with one atomic completion manifest per bank."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import wave

from .audio_download import valid_download
from .io import atomic_write, digest


def wav_metadata(path):
    with wave.open(str(path), 'rb') as file:
        return {'sample_rate': file.getframerate(), 'channels': file.getnchannels(),
                'sample_count': file.getnframes(), 'sample_width': file.getsampwidth()}


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def decode_bank(item, companion, directory, decoder, decoder_sha256, wait_seconds=0):
    directory = Path(directory).resolve()
    bank = directory / 'banks' / item['name']
    stem = Path(item['name']).stem
    done_path = directory / 'bank-manifests' / (stem + '.json')
    final_dir = directory / 'clips' / stem
    if done_path.exists():
        previous = json.loads(done_path.read_text())
        expected = {item['name']: item['md5']}
        if companion:
            expected[companion['name']] = companion['md5']
        if previous.get('source_md5') == expected and previous.get('decoder_sha256') == decoder_sha256:
            if all((directory / r['path']).is_file() and
                   (directory / r['path']).stat().st_size == r['bytes'] and
                   file_digest(directory / r['path']) == r['sha256'] for r in previous['clips']):
                return {'bank': stem, 'status': 'cached', 'clips': len(previous['clips'])}
    deadline = time.monotonic() + wait_seconds
    while not bank.is_file() or (companion and not (directory / 'banks' / companion['name']).is_file()):
        if time.monotonic() >= deadline:
            return {'bank': stem, 'status': 'failed', 'error': 'source_not_downloaded'}
        time.sleep(1)
    for source in [item] + ([companion] if companion else []):
        if not valid_download(directory / 'banks' / source['name'], source):
            return {'bank': stem, 'status': 'failed', 'error': 'source_checksum_mismatch'}
    staging_root = directory / '.staging'
    staging_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=stem + '-', dir=staging_root))
    try:
        # Numeric filenames avoid cue-name collisions and untrusted path separators.
        result = subprocess.run([str(Path(decoder).resolve()), '-I', '-i', '-S', '0',
                                 '-o', str(stage / '?04s.wav'), str(bank)],
                                capture_output=True, text=True, timeout=600)
        if result.returncode:
            return {'bank': stem, 'status': 'failed', 'error': 'decoder_failed',
                    'decoder_returncode': result.returncode}
        metadata = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        if not metadata:
            raise ValueError('decoder_returned_no_metadata')
        clips = []
        indexes = set()
        for row in metadata:
            stream = row.get('streamInfo') or {}
            index = stream.get('index', 0)
            if index in indexes:
                raise ValueError('duplicate_stream_index')
            indexes.add(index)
            wav_path = stage / f'{index:04}.wav'
            info = wav_metadata(wav_path)
            expected_samples = row.get('playSamples', row.get('numberOfSamples'))
            if info['sample_count'] != expected_samples or info['sample_rate'] != row['sampleRate']:
                raise ValueError('wav_metadata_mismatch')
            cue_name = stream.get('name') or None
            clips.append({'id': stem + ':' + str(index), 'bank': stem,
                          'cue_name': cue_name, 'stream_index': index,
                          'path': str((final_dir / wav_path.name).relative_to(directory)),
                          'bytes': wav_path.stat().st_size, 'sha256': file_digest(wav_path),
                          **info, 'duration_ms': round(info['sample_count'] * 1000 / info['sample_rate'], 3),
                          'encoding': row.get('encoding')})
        declared_total = (metadata[0].get('streamInfo') or {}).get('total', 1)
        if len(clips) != declared_total or len(list(stage.glob('*.wav'))) != len(clips):
            raise ValueError('incomplete_bank_extraction')
        # Complete files first; completion marker is published last. Sources are never removed.
        final_dir.mkdir(parents=True, exist_ok=True)
        for file in stage.glob('*.wav'):
            os.replace(file, final_dir / file.name)
        source_md5 = {item['name']: item['md5']}
        if companion:
            source_md5[companion['name']] = companion['md5']
        manifest = {'bank': stem, 'source_md5': source_md5, 'decoder_sha256': decoder_sha256,
                    'decoder_version': metadata[0].get('version'), 'clips': clips}
        atomic_write(done_path, manifest)
        return {'bank': stem, 'status': 'decoded', 'clips': len(clips)}
    except (ValueError, OSError, wave.Error, subprocess.TimeoutExpired) as exc:
        return {'bank': stem, 'status': 'failed', 'error': type(exc).__name__, 'detail': str(exc)[:200]}
    finally:
        shutil.rmtree(stage)


def extract_plan(plan, directory, decoder, workers=6, wait_seconds=0):
    directory = Path(directory)
    decoder_sha256 = file_digest(decoder)
    resources = {r['name']: r for r in plan['resources']}
    banks = [r for r in plan['resources'] if r['name'].endswith('.acb')]
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(decode_bank, row, resources.get(Path(row['name']).stem + '.awb'),
                               directory, decoder, decoder_sha256, wait_seconds) for row in banks]
        for future in as_completed(futures):
            results.append(future.result())
            if len(results) % 100 == 0 or len(results) == len(futures):
                print(json.dumps({'completed': len(results), 'total': len(futures),
                                  'clips': sum(r.get('clips', 0) for r in results),
                                  'statuses': dict(Counter(r['status'] for r in results))}), flush=True)
    report = {'manifest_revision': plan['manifest_revision'], 'decoder_sha256': decoder_sha256,
              'results': sorted(results, key=lambda r: r['bank'])}
    atomic_write(directory / 'extraction-report.json', report)
    # Only include manifests verified during this run; exclude obsolete bank manifests.
    clips = []
    for result in report['results']:
        if result['status'] != 'failed':
            path = directory / 'bank-manifests' / (result['bank'] + '.json')
            clips.extend(json.loads(path.read_text())['clips'])
    atomic_write(directory / 'audio-files.json', {'schema_version': '1.0.0',
                 'manifest_revision': plan['manifest_revision'], 'decoder_sha256': decoder_sha256,
                 'clips': sorted(clips, key=lambda r: r['id'])})
    return report


def main():
    parser = argparse.ArgumentParser(description='Extract verified cue names and WAV audio from planned banks')
    parser.add_argument('--directory', type=Path, default=Path('data/audio'))
    parser.add_argument('--decoder', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--wait-for-downloads', type=int, default=0, metavar='SECONDS')
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        parser.error('--workers must be between 1 and 16')
    plan = json.loads((args.directory / 'download-plan.json').read_text())
    result = extract_plan(plan, args.directory, args.decoder, args.workers, args.wait_for_downloads)
    return int(any(r['status'] == 'failed' for r in result['results']))


if __name__ == '__main__':
    raise SystemExit(main())
