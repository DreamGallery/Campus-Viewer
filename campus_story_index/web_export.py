"""Publish small, versioned web shards without embedding raw masterdata."""
from .web_voice import chapter_voices
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import os
import shutil
import tempfile
import subprocess
import yaml
from .io import atomic_write
from .web_assets import EVENT_COVER_ALTERNATIVES
from .pending_text import filename_hints


def canonical_directory_entries(entries, groups):
    """Deduplicate event/dearness entry points, retaining all chapter sources."""
    group_scripts = defaultdict(set)
    candidates = defaultdict(list)
    for entry in entries:
        if entry['category_id'].startswith('event.') or entry['category_id'] == 'character.dearness':
            candidates[entry['script_id']].append(entry)
            for gid in entry['group_ids']:
                if groups.get(gid, {}).get('kind') == 'story_group':
                    group_scripts[gid].add(entry['script_id'])
    def rank(entry):
        size = max((len(group_scripts[g]) for g in entry['group_ids']), default=0)
        return (-size, entry['order'], entry['id'])
    return {script: sorted(rows, key=rank)[0]['id'] for script, rows in candidates.items()}, {
        script: sorted(row['id'] for row in rows) for script, rows in candidates.items()
    }


def release_time(record, condition_sets):
    """Known display/opening time in milliseconds; never a file modification time.

    TimeTerm.beforeTime is the interval START (afterTime is its end).
    Mixed OR branches cannot establish a single release date, so leave unknown.
    """
    direct = int(record.get('viewStartTime') or 0)
    if direct > 0:
        return direct
    for field in ('viewConditionSetId', 'unlockConditionSetId'):
        rows = condition_sets.get(record.get(field), [])
        if any(r.get('conditionOperatorType') == 'ConditionOperatorType_Or' for r in rows):
            continue
        starts = [int(r.get('beforeTime') or 0) for r in rows
                  if r.get('conditionType') == 'ConditionType_TimeTerm']
        if starts and max(starts) > 0:
            return max(starts)
    return None


def text_update_times(stories, revision):
    if stories is None or not revision:
        return {}
    result = subprocess.run(['git', '-C', str(stories), '-c', 'safe.directory=' + str(Path(stories).resolve()), '-c', 'core.quotepath=false',
        'log', '--format=TIME:%ct', '--name-only', revision, '--', 'CSV'],
        check=True, capture_output=True, text=True)
    dates = {}
    timestamp = None
    for line in result.stdout.splitlines():
        if line.startswith('TIME:'):
            timestamp = int(line[5:]) * 1000
        elif line.startswith('CSV/') and line.endswith('.csv') and timestamp:
            dates[line] = max(timestamp, dates.get(line, 0))
    return dates


def text_changes(stories, revision):
    if stories is None or not revision:
        return {}
    output = subprocess.check_output(['git', '-C', str(stories), '-c',
        'safe.directory=' + str(Path(stories).resolve()), '-c', 'core.quotepath=false',
        'log', '--format=CHANGE:%ct:%H', '--name-status', '--no-renames', revision, '--', 'CSV'], text=True)
    changes = {}
    current = None
    for line in output.splitlines():
        if line.startswith('CHANGE:'):
            _, timestamp, commit = line.split(':')
            current = {'at': int(timestamp) * 1000, 'commit': commit}
        elif current and '\t' in line:
            status, path = line.split('\t', 1)
            if path.endswith('.csv') and status in ('A', 'M'):
                if path not in changes or current['at'] > changes[path]['at']:
                    changes[path] = {**current, 'kind': 'added' if status == 'A' else 'modified'}
    return changes


def build(catalog_path, masterdata, assets_path, voice_path, output, stories=None):
    catalog_bytes = catalog_path.read_bytes()
    catalog = json.loads(catalog_bytes)
    asset_bytes = assets_path.read_bytes()
    asset_info = {r['name']: r for r in json.loads(asset_bytes)['images'] if r.get('path')}
    assets = {r['name']: '/assets/' + r['path'] for r in json.loads(asset_bytes)['images'] if r.get('path')}
    voice_bytes = voice_path.read_bytes()
    voice_manifest = json.loads(voice_bytes)
    if voice_manifest['sources']['catalog_sha256'] != hashlib.sha256(catalog_bytes).hexdigest():
        raise ValueError('Voice index was built from a different story catalog')
    voices = {r['script_id']: r for r in voice_manifest['scripts']}
    source_bytes = [catalog_bytes, asset_bytes, voice_bytes, Path(__file__).read_bytes()]
    source_paths = [catalog_path, assets_path, voice_path, Path(__file__)]
    tables = {}
    for name in ['CharacterDetail', 'CharacterColor']:
        content = (masterdata / (name + '.yaml')).read_bytes()
        tables[name] = yaml.safe_load(content)
        source_bytes.append(content)
        source_paths.append(masterdata / (name + '.yaml'))
    updated = text_update_times(stories, catalog.get('sources', {}).get('stories', {}).get('git_commit'))
    changes = text_changes(stories, catalog.get('sources', {}).get('stories', {}).get('git_commit'))
    source_paths.append(Path(__file__).with_name('web_voice.py'))
    source_bytes.append(source_paths[-1].read_bytes())
    source_paths.append(Path(__file__).with_name('pending_text.py'))
    source_bytes.append(source_paths[-1].read_bytes())
    source_bytes.append(json.dumps([updated, changes], sort_keys=True).encode())
    build_id = hashlib.sha256(b'\0'.join(source_bytes)).hexdigest()[:20]
    root = output / 'builds' / build_id
    output.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.build-', dir=output))
    scripts = {s['id']: s for s in catalog['scripts']}
    groups = {g['id']: g for g in catalog['groups']}
    categories = {c['id']: c for c in catalog['categories']}
    characters = []
    records = {r['id']: r['data'] for r in catalog['source_records']}
    for c in catalog['characters']:
        if not c['is_playable']:
            continue
        ident = c['id']; record = records['Character:' + ident]
        details = {r['type'].removeprefix('CharacterDetailType_'): str(r['content']) for r in tables['CharacterDetail'] if r['characterId'] == ident}
        color = next((r['mainColor'] for r in tables['CharacterColor'] if r['characterId'] == ident), 'D59C43')
        characters.append({'id': ident, 'name': c['name'], 'first_name': record['firstName'],
            'english_name': (record['alphabetFirstName'] + ' ' + record['alphabetLastName']).title(),
            'color': '#' + str(color), 'details': details,
            'portrait': assets.get(f'img_chr_{ident}_00-full'),
            'avatar': assets.get(f'img_chr_{ident}_00-thumb-circle'),
            'signature': assets.get(f'img_general_sign_{ident}_00')})
    def entry_metadata(entry, group):
        record = records.get(entry.get('source_record_id'), {})
        released = release_time(record, catalog.get('condition_sets', {}))
        current = group
        seen = set()
        card = {}
        while current and current['id'] not in seen:
            seen.add(current['id'])
            data = records.get(current.get('source_record_id'), {})
            if current['kind'] == 'support_card':
                card = data
            if released is None:
                released = release_time(data, catalog.get('condition_sets', {}))
            current = groups.get(current.get('parent_id'))
        return {'release_at': released,
                'support_rarity': card.get('rarity', '').removeprefix('SupportCardRarity_').upper() or None,
                'support_attribute': card.get('type', '').removeprefix('SupportCardType_') or None,
                'card_character_ids': card.get('characterIds', [])}

    def images_for(group):
        # Main chapter covers belong to the ancestor, not the internal StoryGroup.
        ancestor = group
        seen = set()
        while ancestor and ancestor['id'] not in seen:
            seen.add(ancestor['id'])
            if ancestor['kind'] == 'main_chapter':
                record = records.get(ancestor.get('source_record_id'), {})
                cover = assets.get('img_general_commu_chapter-thumb_' + str(record.get('storyAssetId', '')))
                return [{'url': cover, 'label': '章节封面', 'aspect_ratio': 2}] if cover else []
            ancestor = groups.get(ancestor.get('parent_id'))
        name = group['image_asset_id']
        if name and name.endswith('-story-banner'):
            candidates = [name, name.removesuffix('-story-banner') + '-banner', EVENT_COVER_ALTERNATIVES.get(name)]
            available = [key for key in candidates if key in asset_info]
            if available:
                name = max(available, key=lambda key: asset_info[key].get('width', 0) * asset_info[key].get('height', 0))
            info = asset_info.get(name, {})
            ratio = info['width'] / info['height'] if info.get('height') else None
            return [{'url': assets[name], 'label': '活动封面', 'aspect_ratio': ratio, 'preview_crop': '50% 42%' if name.endswith('-story-header') else None}] if name in assets else []
        if group['kind'] == 'idol_card':
            candidates = [(f'img_general_{name}_{stage}-full', f'阶段 {stage + 1}') for stage in (0, 1)]
        elif group['kind'] == 'support_card':
            candidates = [(f'img_general_{name}_full', '卡面')]
        else:
            candidates = [(name, '预览')]
        ratio = 9 / 16 if group['kind'] == 'idol_card' else 16 / 9 if group['kind'] == 'support_card' else None
        return [{'url': assets[key], 'label': label, 'aspect_ratio': ratio} for key, label in candidates if key in assets]
    def image_for(group):
        images = images_for(group)
        return images[0]['url'] if images else None
    def group_title(group):
        chain = []; current = group; seen = set()
        while current and current['id'] not in seen:
            seen.add(current['id']); chain.insert(0, current)
            current = groups.get(current.get('parent_id'))
        main = [g for g in chain if g['kind'] in ('main_part', 'main_chapter')]
        if main:
            return ' / '.join(g['title'] for g in main)
        titles = []
        for g in chain:
            if g['kind'] != 'character' and (not titles or titles[-1] != g['title']):
                titles.append(g['title'])
        return ' / '.join(titles)
    priorities = ['idol_card', 'support_card', 'main_chapter', 'story_group', 'event', 'produce_mode', 'character', 'main_part', 'produce_story_family']
    preferred_events, event_sources = canonical_directory_entries(catalog["entries"], groups)
    shards = defaultdict(list)
    chapters = defaultdict(list)
    for e in catalog['entries']:
        available = [groups[g] for g in e['group_ids'] if g in groups]
        available.sort(key=lambda g: (priorities.index(g['kind']), g['order'], g['id']))
        g = available[0] if available else None
        s = scripts[e['script_id']]
        item = {k:e[k] for k in ['id','script_id','title','category_id','character_ids','order']}
        if e['category_id'].startswith('character.') and not item['character_ids']:
            item['character_ids'] = e.get('inferred_character_ids', [])
        item.update({'group_id': g['id'] if g else e['category_id'],
            'group_title': group_title(g) if g and g['kind'] not in ('character','produce_story_family') else categories[e['category_id']]['name'],
            'group_order': g['order'] if g else 0, 'group_image': image_for(g) if g else None,
            'group_images': images_for(g) if g else [],
            'text_status': s['text_status'], 'line_count': s['text_row_count']})
        item.update(entry_metadata(e, g))
        item['text_updated_at'] = updated.get(s.get('csv_path'))
        if item['card_character_ids']:
            item['character_ids'] = sorted(set(item['character_ids']) | set(item['card_character_ids']))
        category = e['category_id'].split('.')[0]
        deduplicate = category == 'event' or e['category_id'] == 'character.dearness'
        if not deduplicate or preferred_events[e['script_id']] == e['id']:
            directory_item = {**item, 'source_entry_ids': event_sources[e['script_id']]} if deduplicate else item
            shards[category].append(directory_item)
            if category == 'character':
                for ident in item['character_ids']:
                    shards['character-' + ident].append(directory_item)
        chapters[e['script_id']].append({**item, 'conditions': e['conditions'], 'context': e['context']})
    entries_by_script = defaultdict(list)
    for entry in catalog['entries']:
        entries_by_script[entry['script_id']].append(entry)
    updates = []
    for ident, variants in chapters.items():
        script = scripts[ident]
        if script['text_status'] == 'empty' or not script.get('csv_path'):
            continue
        source_entries = entries_by_script[ident]
        pending = script.get('metadata_status') == 'unlinked_masterdata' or all(not e.get('source_record_id') or e['source_record_id'].startswith('AssetDownload:') for e in source_entries)
        row = variants[0]
        hints = filename_hints(ident, [c['id'] for c in catalog['characters']])
        previews = row['group_images']
        if pending:
            previews = [{'url': assets[name], 'label': '文件名匹配预览', 'aspect_ratio': ratio}
                        for name, ratio in hints['images'] if name in assets]
        change = changes.get(script['csv_path'], {})
        updates.append({'script_id': ident, 'entry_id': row['id'],
            'title': row['title'] if not pending else '名称待补全',
            'group_title': row['group_title'] if not pending else None,
            'category_id': (hints['category_id'] or row['category_id']) if pending else row['category_id'],
            'character_ids': hints['character_ids'] if pending else row['character_ids'],
            'pending': pending, 'inference_basis': 'filename' if pending else None,
            'images': previews, 'csv_path': script['csv_path'],
            'line_count': script['text_row_count'], 'updated_at': updated.get(script['csv_path']),
            'change_kind': change.get('kind'), 'commit': change.get('commit')})
    updates.sort(key=lambda row: (-(row['updated_at'] or 0), row['script_id']))
    update_by_script = {row['script_id']: row for row in updates}
    try:
        atomic_write(stage / 'updates.json', {'items': updates,
            'source_commit': catalog.get('sources', {}).get('stories', {}).get('git_commit'),
            'pending_count': sum(row['pending'] for row in updates)})
        for name, rows in shards.items():
            rows.sort(key=lambda r: (list(categories).index(r['category_id']), r['group_order'], r['group_id'], r['order'], r['id']))
            atomic_write(stage / 'lists' / (name + '.json'), rows)
        for ident, entries in chapters.items():
            s = scripts[ident]
            atomic_write(stage / 'chapters' / (ident + '.json'), {
                'script_id': ident, 'entries': entries, 'csv_path': s['csv_path'],
                'voices': chapter_voices(voice_path.parent, voices.get(ident)),
                'metadata_pending': update_by_script.get(ident, {}).get('pending', False),
                'group_images': update_by_script.get(ident, {}).get('images', entries[0]['group_images']),
            'text_status': s['text_status'], 'line_count': s['text_row_count'],
                'translated_line_count': s['translated_row_count'],
                'voice_event_count': voices.get(ident, {}).get('voice_event_count', 0)})
        info = {'schema_version': '1.0', 'build_id': build_id,
                'resource_revision': json.loads(asset_bytes).get('revision'),
                'base_path': '/catalog/builds/' + build_id, 'characters': characters,
                'speaker_avatars': [{'id': c['id'], 'name': c['name'],
                    'aliases': list(dict.fromkeys(n for n in [c['name'],
                        records.get('Character:' + c['id'], {}).get('firstName', ''),
                        records.get('Character:' + c['id'], {}).get('lastName', '')] if n)),
                    'avatar': assets.get(f"img_chr_{c['id']}_00-thumb-circle")}
                    for c in catalog['characters'] if assets.get(f"img_chr_{c['id']}_00-thumb-circle")],
                'filter_characters': [{'id': c['id'], 'name': c['name'],
                    'stamp_unselected': assets.get(f"img_general_stamp_{c['id']}-01"),
                    'stamp_selected': assets.get(f"img_general_stamp_{c['id']}-02")} for c in catalog['characters']],
                'categories': catalog['categories'], 'entry_count': len(catalog['entries']),
                'script_count': len(catalog['scripts']), 'updates_path': 'updates.json',
                'pending_text_count': sum(row['pending'] for row in updates),
                'lists': {k: 'lists/' + k + '.json' for k in shards}}
        root.parent.mkdir(parents=True, exist_ok=True)
        if any(path.read_bytes() != content for path, content in zip(source_paths, source_bytes)):
            raise ValueError('Input changed during web export')
        for path in [stage, *stage.rglob('*')]:
            path.chmod(0o755 if path.is_dir() else 0o644)
        if root.exists():
            for file in stage.rglob('*.json'):
                if (root / file.relative_to(stage)).read_bytes() != file.read_bytes():
                    raise ValueError('Non-deterministic export')
        else:
            os.replace(stage, root)
        atomic_write(output / 'manifest.json', info)
        (output / 'manifest.json').chmod(0o644)
        return info
    finally:
        if stage.exists(): shutil.rmtree(stage)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--catalog',type=Path,default=Path('generated/story-index.json'))
    p.add_argument('--masterdata',type=Path,required=True)
    p.add_argument('--assets',type=Path,default=Path('data/web/assets/manifest.json'))
    p.add_argument('--voices',type=Path,default=Path('generated/voice-index/manifest.json'))
    p.add_argument('--output',type=Path,default=Path('data/web/catalog'))
    p.add_argument('--stories', type=Path, help='Campus-Story Git checkout for committed text update dates')
    a=p.parse_args(); result=build(a.catalog,a.masterdata,a.assets,a.voices,a.output,a.stories)
    print(json.dumps({k:result[k] for k in ['build_id','script_count','entry_count']}))

if __name__=='__main__': main()
