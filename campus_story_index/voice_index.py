"""Join CSV text -> ADV events -> verified bank cue metadata, with conservative ambiguity handling."""
import argparse
from collections import Counter, defaultdict
import csv
from functools import lru_cache
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from .adv import parse_script
from .io import Snapshot, atomic_write, canonical, digest

VOICE_FIELDS = {'{voice_asset_id}': 'voiceAssetId',
                '{voice_asset_id_01}': 'voiceAssetId1', '{voice_asset_id_02}': 'voiceAssetId2'}


def csv_rows(content):
    reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig'), newline=''))
    if not reader.fieldnames or not {'id', 'name', 'text', 'trans'} <= set(reader.fieldnames):
        raise ValueError('Invalid CSV header')
    rows = []
    previous_line = reader.line_num
    for index, row in enumerate(reader, 1):
        start_line = previous_line + 1
        previous_line = reader.line_num
        if None in row or any(row.get(k) is None for k in ['id', 'name', 'text', 'trans']):
            raise ValueError('Invalid CSV record')
        if row['id'] in ('info', '译者') or not row['text'].strip():
            continue
        rows.append({'csv_record_index': index, 'csv_line_start': start_line,
                     'csv_line_end': reader.line_num, 'csv_id': row['id'],
                     'speaker': row['name'], 'text': row['text'], 'translation': row['trans'],
                     'kind': 'choice' if row['id'] == 'select' else 'dialogue'})
    return rows


def text_key(row, source=False, normalize=False):
    kind = 'choice' if row['kind'] == 'choice' else 'dialogue'
    speaker = row['speaker']
    if normalize and speaker == '__narration__':
        speaker = ''
    return kind, speaker, row['text']


def align_csv(rows, source_texts):
    """Never pair by row number alone. Equal complete sequences may include repeated text."""
    left = [text_key(r) for r in rows]
    right = [text_key(r, True) for r in source_texts]
    if left == right:
        return {i: i for i in range(len(rows))}, 'exact_sequence', {}
    left = [text_key(r, normalize=True) for r in rows]
    right = [text_key(r, True, normalize=True) for r in source_texts]
    if left == right:
        return {i: i for i in range(len(rows))}, 'normalized_narrator_sequence', {}
    a, b = defaultdict(list), defaultdict(list)
    for i, key in enumerate(left):
        a[key].append(i)
    for i, key in enumerate(right):
        b[key].append(i)
    mapping, candidates = {}, {}
    for key, indexes in a.items():
        if len(indexes) == 1 and len(b[key]) == 1:
            mapping[indexes[0]] = b[key][0]
        else:
            for index in indexes:
                candidates[index] = b[key]
    return mapping, 'partial_unique_text', candidates


def speaker_resolver(characters):
    patterns = [(c['id'], re.compile(p)) for c in characters
                if any(s.startswith('Character:') for s in c['source_record_ids'])
                for p in c['speaker_patterns']]
    names = defaultdict(set)
    for c in characters:
        for name in [c['name'], *c['speaker_names']]:
            names[name].add(c['id'])
    @lru_cache(maxsize=2048)
    def resolve(name):
        result = set(names.get(name, set()))
        result.update(cid for cid, pattern in patterns if pattern.search(name))
        return frozenset(result)
    return resolve


def voice_character(voice, character_ids):
    cue = voice['voice_ref'] or ''
    match = re.search(r'_([a-z0-9]+)-\d+$', cue) or re.search(r'_part_([a-z0-9]+)_\d+$', cue)
    if match and match[1] in character_ids:
        return match[1]
    # actorId controls lip/actor animation and is only a fallback identity hint.
    return voice['actor_id'] if voice['actor_id'] in character_ids else None


def match_voice(voice, texts, resolve_speaker, character_ids):
    if not voice['timing'] or not voice.get('voice_ref'):
        return {'status': 'no_timing_or_reference', 'text_ids': [], 'context_text_ids': [], 'candidate_text_ids': []}
    start = voice['timing']['start_ms']
    actor = voice_character(voice, character_ids)
    candidates = []
    for text in texts:
        if text['kind'] == 'choice' or text['scope'] != voice['scope'] or not text['timing']:
            continue
        timing = text['timing']
        delta = start - timing['start_ms']
        # 150 ms permits small authored voice pre-roll; never cross branch/timeline scopes.
        if delta < -150 or delta > timing['duration_ms'] + 30:
            continue
        speaker_ids = resolve_speaker(text['speaker'])
        conflict = text['speaker'] == '{user}' or bool(actor and speaker_ids and actor not in speaker_ids)
        candidates.append((text, delta, conflict))
    compatible = [(t, delta) for t, delta, conflict in candidates if not conflict]
    close = [(t, delta) for t, delta in compatible if -150 <= delta <= 250]
    selected = close if len(close) == 1 else compatible
    if len(selected) == 1:
        text, delta = selected[0]
        return {'status': 'matched_temporally', 'text_ids': [text['id']],
                'context_text_ids': [], 'candidate_text_ids': [t['id'] for t, _, _ in candidates],
                'method': 'start_proximity' if len(close) == 1 else 'unique_time_window',
                'start_delta_ms': round(delta, 6),
                'speaker_evidence': 'consistent' if actor and actor in resolve_speaker(text['speaker']) else 'unknown'}
    context = [t['id'] for t, _, _ in candidates] if len(candidates) == 1 and not compatible else []
    return {'context_text_ids': context, 'status': 'ambiguous' if compatible else 'speaker_conflict' if candidates else 'no_text_in_scope',
            'text_ids': [], 'candidate_text_ids': [t['id'] for t, _, _ in candidates]}


def audio_variants(voice, entries, cue_banks, clips_by_key):
    reference = voice['voice_ref']
    if not reference:
        return []
    bindings = defaultdict(list)
    if reference.startswith('sud_'):
        bindings[reference] = []
    elif reference in VOICE_FIELDS:
        field = VOICE_FIELDS[reference]
        for entry in entries:
            for binding in entry['voice_bindings']:
                if binding['source_field'] == field:
                    bindings[binding['asset_id']].append(entry)
    else:
        return [{'voice_ref': reference, 'status': 'unresolved_parameter', 'entry_ids': [],
                 'character_ids': [], 'audio_file_id': None, 'audio_path': None}]
    variants = []
    for cue, contexts in sorted(bindings.items()):
        bank = cue_banks.get(cue)
        matches = clips_by_key.get((bank, cue), [])
        status = 'verified' if len(matches) == 1 else 'ambiguous_cue' if matches else 'cue_not_found'
        clip = matches[0] if status == 'verified' else None
        variants.append({'voice_ref': cue, 'bank': bank, 'status': status,
                         'entry_ids': sorted(e['id'] for e in contexts),
                         'character_ids': sorted({c for e in contexts for c in e['character_ids']}),
                         'audio_file_id': clip['id'] if clip else None,
                         'audio_path': clip['path'] if clip else None,
                         'audio_duration_ms': clip['duration_ms'] if clip else None})
    if not variants:
        variants.append({'voice_ref': reference, 'status': 'unresolved_parameter', 'entry_ids': [],
                         'character_ids': [], 'audio_file_id': None, 'audio_path': None})
    return variants


def make_script(script_id, csv_content, adv_content, entries, characters, cue_banks, clips_by_key, resolve):
    rows = csv_rows(csv_content) if csv_content is not None else []
    parsed = parse_script(adv_content.decode('utf-8-sig'), script_id) if adv_content is not None else {
        'texts': [], 'voices': [], 'embedded_timelines': []}
    texts, voices = parsed['texts'], parsed['voices']
    mapping, alignment, candidates = align_csv(rows, texts)
    if adv_content is None and csv_content is None:
        alignment = 'missing_csv_and_adv'
    elif adv_content is None:
        alignment = 'missing_adv'
    elif csv_content is None:
        alignment = 'missing_csv'
    voice_by_text = defaultdict(list)
    context_by_text = defaultdict(list)
    diagnostics = []
    for voice in voices:
        voice['text_match'] = match_voice(voice, texts, resolve, characters)
        voice['audio_variants'] = audio_variants(voice, entries, cue_banks, clips_by_key)
        reference = voice['voice_ref'] or ''
        voice['voice_kind'] = ('reaction' if reference.startswith('sud_vo_general_part_') else
                               'dialogue' if reference.startswith('sud_vo_adv_') else
                               'dynamic' if reference.startswith('{') else 'system_or_other')
        for tid in voice['text_match']['text_ids']:
            voice_by_text[tid].append(voice)
        for tid in voice['text_match']['context_text_ids']:
            context_by_text[tid].append(voice)
        if voice['text_match']['status'] in ('ambiguous', 'speaker_conflict'):
            diagnostics.append({'code': 'voice_text_' + voice['text_match']['status'], 'voice_event_id': voice['id']})
        for variant in voice['audio_variants']:
            if variant['status'] != 'verified':
                diagnostics.append({'code': variant['status'], 'voice_event_id': voice['id'], 'voice_ref': variant['voice_ref']})
    lines, occurrence = [], Counter()
    for index, row in enumerate(rows):
        source = texts[mapping[index]] if index in mapping else None
        fingerprint = digest(canonical([row['kind'], row['speaker'], row['text']]).encode())[:24]
        occurrence[fingerprint] += 1
        linked = voice_by_text[source['id']] if source else []
        if source:
            line_id = source['id']
            matched = 'matched' if alignment in ('exact_sequence', 'normalized_narrator_sequence') else 'unique_text'
        else:
            line_id = f'{script_id}/csv/{fingerprint}/{occurrence[fingerprint]}'
            matched = 'ambiguous' if candidates.get(index) else 'unmatched'
        audio_status = ('choice' if row['kind'] == 'choice' else
                        'csv_unmatched' if not source else
                        'linked' if linked and all(v['audio_variants'] and all(a['status'] == 'verified' for a in v['audio_variants']) for v in linked) else
                        'audio_unavailable' if linked else
                        'context_audio_only' if source and context_by_text[source['id']] else 'no_explicit_voice')
        lines.append({'id': line_id, **row, 'csv_match_status': matched,
                      'source_line': source['source_line'] if source else None,
                      'source_kind': source['kind'] if source else None,
                      'scope': source['scope'] if source else None,
                      'timing': source['timing'] if source else None,
                      'voice_event_ids': [v['id'] for v in linked],
                      'context_voice_event_ids': [v['id'] for v in context_by_text[source['id']]] if source else [],
                      'audio_status': audio_status,
                      'candidate_source_text_ids': [texts[i]['id'] for i in candidates.get(index, [])]})
    mapped = set(mapping.values())
    result = {'schema_version': '1.0.0', 'script_id': script_id,
              'csv_alignment': alignment, 'lines': lines, 'voice_events': voices,
              'source_texts_without_csv': [t for i, t in enumerate(texts) if i not in mapped],
              'embedded_timelines': parsed['embedded_timelines'], 'diagnostics': diagnostics}
    validate_script(result)
    return result


def validate_script(script):
    lines = {r['id']: r for r in script['lines']}
    voices = {r['id']: r for r in script['voice_events']}
    if len(lines) != len(script['lines']) or len(voices) != len(script['voice_events']):
        raise ValueError('Duplicate line/voice event ID')
    for line in lines.values():
        for vid in line['voice_event_ids']:
            if vid not in voices or line['id'] not in voices[vid]['text_match']['text_ids']:
                raise ValueError('Broken voice/line back-reference')
            if line['scope'] != voices[vid]['scope']:
                raise ValueError('Voice crossed branch scope')
        for vid in line['context_voice_event_ids']:
            if vid not in voices or line['id'] not in voices[vid]['text_match']['context_text_ids']:
                raise ValueError('Broken contextual voice link')
        if line['kind'] == 'choice' and (line['voice_event_ids'] or line['context_voice_event_ids']):
            raise ValueError('Choice text assigned a voice')
    for voice in voices.values():
        for variant in voice['audio_variants']:
            if variant['status'] == 'verified' and not variant['audio_path']:
                raise ValueError('Verified audio has no path')


def build_voice_index(catalog_path, stories_root, adv_root, audio_root, output):
    catalog_content = Path(catalog_path).read_bytes()
    catalog = json.loads(catalog_content)
    audio_root, output = Path(audio_root), Path(output)
    plan_content = (audio_root / 'download-plan.json').read_bytes()
    audio_content = (audio_root / 'audio-files.json').read_bytes()
    plan, audio = json.loads(plan_content), json.loads(audio_content)
    if plan['manifest_revision'] != audio['manifest_revision']:
        raise ValueError('Download plan and extraction metadata revisions differ')
    by_key = defaultdict(list)
    for clip in audio['clips']:
        by_key[(clip['bank'], clip['cue_name'])].append(clip)
        path = audio_root / clip['path']
        if not path.is_file() or path.stat().st_size != clip['bytes']:
            raise ValueError(f'Missing or changed extracted audio: {clip["id"]}')
    entries_by_script = defaultdict(list)
    for entry in catalog['entries']:
        entries_by_script[entry['script_id']].append(entry)
    resolve = speaker_resolver(catalog['characters'])
    character_ids = {c['id'] for c in catalog['characters']}
    stories, adv = Snapshot(stories_root), Snapshot(adv_root)
    csv_files = sorted((stories.root / 'CSV').rglob('*.csv'))
    adv_files = sorted(adv.root.rglob('adv_*.txt'))
    def unique_paths(files):
        mapped = {}
        for path in files:
            if path.stem in mapped:
                raise ValueError(f'Duplicate input basename: {path.stem}')
            mapped[path.stem] = path
        return mapped
    csv_by_id, adv_by_id = unique_paths(csv_files), unique_paths(adv_files)
    script_ids = sorted({r['id'] for r in catalog['scripts']} | csv_by_id.keys() | adv_by_id.keys())
    output.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.build-', dir=output))
    (stage / 'scripts').mkdir()
    summaries, diagnostics = [], []
    counts = {name: Counter() for name in ['csv_alignment', 'csv_match', 'line_audio', 'voice_text', 'voice_audio', 'voice_kind']}
    try:
        for number, sid in enumerate(script_ids, 1):
            if not re.fullmatch(r'[A-Za-z0-9_\-]+', sid):
                raise ValueError('Unsafe script ID')
            csv_path, adv_path = csv_by_id.get(sid), adv_by_id.get(sid)
            csv_relative = str(csv_path.relative_to(stories.root)) if csv_path else None
            adv_relative = str(adv_path.relative_to(adv.root)) if adv_path else None
            csv_content = stories.read(csv_relative) if csv_path else None
            adv_content = adv.read(adv_relative) if adv_path else None
            if csv_relative and catalog['sources']['stories']['files'].get(csv_relative) != digest(csv_content):
                raise ValueError('CSV changed since story catalog build; rebuild the story catalog first')
            if adv_relative and plan['adv_hashes'].get(adv_relative) != digest(adv_content):
                raise ValueError('ADV changed since download plan; rebuild the voice plan first')
            result = make_script(sid, csv_content, adv_content, entries_by_script[sid],
                                 character_ids, plan['cue_banks'], by_key, resolve)
            result['sources'] = {'csv_path': csv_relative, 'csv_sha256': digest(csv_content) if csv_content else None,
                                 'adv_path': adv_relative, 'adv_sha256': digest(adv_content) if adv_content else None}
            atomic_write(stage / 'scripts' / (sid + '.json'), result)
            counts['csv_alignment'][result['csv_alignment']] += 1
            counts['csv_match'].update(r['csv_match_status'] for r in result['lines'])
            counts['line_audio'].update(r['audio_status'] for r in result['lines'])
            counts['voice_text'].update(r['text_match']['status'] for r in result['voice_events'])
            counts['voice_kind'].update(r['voice_kind'] for r in result['voice_events'])
            counts['voice_audio'].update(a['status'] for r in result['voice_events'] for a in r['audio_variants'])
            diagnostics.extend({'script_id': sid, **d} for d in result['diagnostics'])
            summaries.append({'script_id': sid, 'path': 'scripts/' + sid + '.json',
                              'line_count': len(result['lines']), 'voice_event_count': len(result['voice_events']),
                              'csv_alignment': result['csv_alignment'], 'diagnostic_count': len(result['diagnostics'])})
            if number % 500 == 0:
                print(json.dumps({'scripts_processed': number, 'total': len(script_ids)}), flush=True)
        sources = {'catalog_sha256': digest(catalog_content), 'audio_manifest_sha256': digest(audio_content),
                   'download_plan_sha256': digest(plan_content), 'adv': adv.manifest(), 'stories': stories.manifest()}
        stories.verify()
        adv.verify()
        if csv_files != sorted((stories.root / 'CSV').rglob('*.csv')) or adv_files != sorted(adv.root.rglob('adv_*.txt')):
            raise ValueError('Input file list changed during voice-index build')
        if Path(catalog_path).read_bytes() != catalog_content or (audio_root / 'audio-files.json').read_bytes() != audio_content:
            raise ValueError('Catalog/audio manifest changed during build')
        # Content-addressed builds make the small manifest switch atomic for readers.
        code_hash = digest(b''.join(Path(__file__).with_name(name).read_bytes() for name in ['voice_index.py', 'adv.py']))
        build_id = digest(canonical({'sources': sources, 'code_sha256': code_hash}).encode())[:24]
        destination = output / 'builds' / build_id
        destination.parent.mkdir(exist_ok=True)
        stats = {k: dict(sorted(v.items())) for k, v in counts.items()}
        stats.update({'script_count': len(script_ids), 'audio_file_count': len(audio['clips']),
                      'line_count': sum(s['line_count'] for s in summaries),
                      'voice_event_count': sum(s['voice_event_count'] for s in summaries),
                      'diagnostic_count': len(diagnostics)})
        atomic_write(stage / 'diagnostics.json', diagnostics)
        if destination.exists():
            # Compare same-build files before reusing the immutable directory.
            for path in stage.rglob('*.json'):
                target = destination / path.relative_to(stage)
                if not target.is_file() or path.read_bytes() != target.read_bytes():
                    raise ValueError('Non-deterministic voice-index build')
            shutil.rmtree(stage)
        else:
            os.replace(stage, destination)
        for summary in summaries:
            summary['path'] = f'builds/{build_id}/' + summary['path']
        manifest = {'schema_version': '1.0.0', 'build_id': build_id, 'sources': sources,
                    'matching_rules': {'early_voice_tolerance_ms': 150, 'close_start_limit_ms': 250,
                                       'window_end_tolerance_ms': 30, 'cross_scope_matching': False},
                    'stats': stats, 'scripts': summaries,
                    'diagnostics_path': f'builds/{build_id}/diagnostics.json'}
        atomic_write(output / 'manifest.json', manifest)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description='Build per-script CSV/voice correspondence index')
    parser.add_argument('--catalog', default='generated/story-index.json', type=Path)
    parser.add_argument('--stories', required=True, type=Path)
    parser.add_argument('--adv', required=True, type=Path)
    parser.add_argument('--audio-root', default='data/audio', type=Path)
    parser.add_argument('--output', default='generated/voice-index', type=Path)
    args = parser.parse_args()
    manifest = build_voice_index(args.catalog, args.stories, args.adv, args.audio_root, args.output)
    print(json.dumps(manifest['stats'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
