"""Source adapters build a flat, lossless catalog with explicit browsing relations."""
from collections import Counter, defaultdict
import re

from . import __version__
from .io import MasterData, Snapshot, canonical, digest, read_csvs
from .taxonomy import LEAVES, ROOTS, STORY_TYPES, PRODUCE_TYPES, RELATION_CATEGORIES

# Keys omit mutable titles, conditions, script paths, and physical row positions.
COMPOSITE_KEYS = {
    'CharacterAdv': ['characterId'], 'CharacterDetail': ['characterId', 'type', 'order'],
    'CharacterDearnessLevel': ['characterId', 'dearnessLevel'],
    'CharacterProduceStory': ['characterId', 'produceGroupId'],
    'ProduceStoryGroup': ['id', 'characterId'],
    'ProduceAdv': ['produceType', 'type'],
    'ProduceCharacterAdv': ['produceType', 'type', 'characterId'],
    'ProduceSplitAdv': ['produceType', 'type', 'produceSplitTypes', 'targetCharacterId'],
    'ProduceLive': ['musicId', 'type'],
    'ProduceGroupLiveCommon': ['characterId', 'produceGroupId', 'type', 'musicId'],
    'ProduceStepTransition': ['characterId', 'stepType', 'stepPhaseType', 'number',
                              'produceGroupId', 'produceIds', 'unitCharacterIds'],
    'ProduceStepOpenLessonMotion': ['characterId', 'stepType', 'number'],
    'ProduceWeekMotion': ['characterId', 'number', 'produceIds'],
    'Tutorial': ['tutorialType', 'idolCardId', 'step', 'subStep'],
}
REQUIRED_TABLES = [
    'Story', 'ProduceStory', 'Character', 'CharacterAdv', 'CharacterDearnessLevel',
    'CharacterProduceStory', 'ProduceStoryGroup', 'IdolCard', 'SupportCard', 'StoryGroup',
    'ProduceStepEventDetail', 'ProduceStepEventSuggestion',
    'StoryEvent', 'MainStoryPart', 'MainStoryChapter', 'ProduceGroup', 'ConditionSet',
]
CONDITION_NAMES = {
    'viewConditionSetId': 'visible_if', 'unlockConditionSetId': 'unlocked_if',
    'forceUnlockConditionSetId': 'force_unlocked_if',
    'itemUnlockConditionSetId': 'item_unlocked_if',
}
CONTEXT_NAMES = {
    'dearnessLevel': 'dearness_level', 'produceType': 'produce_type',
    'produceSplitTypes': 'split_type', 'stepType': 'step_type',
    'stepPhaseType': 'step_phase', 'number': 'variant_number',
    'musicId': 'music_id', 'step': 'tutorial_step', 'subStep': 'tutorial_substep',
    'tutorialType': 'tutorial_type', 'isBusinessExcellent': 'is_business_excellent',
    'produceIds': 'produce_ids', 'unitCharacterIds': 'unit_character_ids',
}


def source_key(table, row):
    keys = COMPOSITE_KEYS.get(table)
    if keys:
        if any(k not in row for k in keys):
            raise ValueError(f'{table}: missing composite key field')
        return {k: row[k] for k in keys}, 'explicit'
    if row.get('id'):
        return {'id': row['id']}, 'explicit'
    # Future table fallback is deliberately marked: content edits can change this key.
    return {'content_sha256': digest(canonical(row).encode())}, 'content_hash'


def source_id(table, key):
    if list(key) == ['id']:
        return table + ':' + str(key['id'])
    return table + ':' + digest(canonical(key).encode())[:24]


def literal_refs(value, path=()):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from literal_refs(v, path + (k,))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from literal_refs(v, path + (i,))
    elif isinstance(value, str) and value.startswith('adv_'):
        yield path, value


def conditions(row):
    return {label: row[k] for k, label in CONDITION_NAMES.items() if row.get(k)}


def order_value(row):
    value = row.get('order', row.get('storyGroupOrder', 0))
    return int(value or 0)


class CatalogBuilder:
    def __init__(self, master, stories):
        self.master = MasterData(master)
        self.stories = Snapshot(stories)
        self.sources = {}
        self.entries = {}
        self.scripts = {}
        self.groups = {}
        self.memberships = []
        self.characters = {}
        self.diagnostics = []
        self.row_ids = {}
        self.table_ids = {}
        self.by_script = defaultdict(list)
        self.category_hints = defaultdict(set)
        self.modes_by_type = defaultdict(set)
        self.modes_by_produce = defaultdict(set)
        self.csv_paths = []
        self.extra_dearness_scripts = {
            (r.get('characterId'), r['advAssetId'])
            for r in self.master.table('Story')
            if r.get('type') == 'StoryType_ExtraDearnessStory' and r.get('advAssetId')
        }

    def warn(self, code, **details):
        self.diagnostics.append({'code': code, **details})

    def rows(self, table):
        rows = self.master.table(table)
        if table not in self.table_ids:
            ids = set()
            for row in rows:
                key, strategy = source_key(table, row)
                sid = source_id(table, key)
                if sid in ids:
                    raise ValueError(f'Duplicate source key in {table}: {key}')
                ids.add(sid)
                self.row_ids[id(row)] = (sid, key, strategy)
            self.table_ids[table] = ids
        return rows

    def register(self, table, row):
        if id(row) not in self.row_ids:
            self.rows(table)
        sid, key, strategy = self.row_ids[id(row)]
        if sid not in self.sources:
            self.sources[sid] = {'id': sid, 'table': table, 'key': key,
                                 'key_strategy': strategy, 'data': row}
            if strategy == 'content_hash':
                self.warn('unstable_source_key', source_record_id=sid)
        return sid

    def script(self, asset):
        if asset not in self.scripts:
            self.scripts[asset] = {
                'id': asset, 'asset_id': asset, 'entry_ids': [], 'source_record_ids': [],
                'category_ids': [], 'character_ids': [], 'csv_path': None,
                'file_sha256': None, 'source_text_sha256': None,
                'text_row_count': 0, 'translated_row_count': 0, 'text_status': 'missing',
                'metadata_status': 'referenced',
            }
        return self.scripts[asset]

    def new_group(self, table, row, kind, parent=None, chars=()):
        sid = self.register(table, row)
        self.groups[sid] = {
            'id': sid, 'kind': kind, 'title': row.get('title', row.get('name')) or row.get('id', sid),
            'title_language': 'ja', 'parent_id': parent,
            'order': order_value(row), 'character_ids': sorted(set(chars)),
            'image_asset_id': next((row[k] for k in ['storyThumbnailAssetId', 'bannerAssetId', 'assetId'] if row.get(k)), None),
            'conditions': conditions(row), 'source_record_id': sid,
            'metadata': {label: row[k] for k, label in {
                'rarity': 'rarity', 'isLimited': 'is_limited', 'description': 'description',
                'viewStartTime': 'available_from', 'type': 'source_type', 'storyType': 'source_type',
                'dearnessLevelMin': 'dearness_level_min', 'dearnessLevelMax': 'dearness_level_max',
            }.items() if k in row},
        }
        return sid

    def prepare_entities(self):
        for table in REQUIRED_TABLES:
            # ConditionSet intentionally has repeated IDs; serialized separately below.
            if table != 'ConditionSet':
                self.rows(table)
            else:
                self.master.table(table)
        for table in ('Story', 'ProduceStory'):
            for row in self.rows(table):
                if not isinstance(row.get('advAssetId'), str) or not row['advAssetId'].startswith('adv_'):
                    raise ValueError(f'{table}: missing or invalid script asset for {row.get("id")}')
        for row in self.rows('Character'):
            sid = self.register('Character', row)
            self.characters[row['id']] = {
                'id': row['id'], 'name': ' '.join(filter(None, [row.get('lastName'), row.get('firstName')])),
                'is_playable': row.get('isPlayable', False), 'speaker_names': [],
                'speaker_patterns': [], 'order': order_value(row), 'source_record_ids': [sid],
            }
        for row in self.rows('CharacterAdv'):
            sid = self.register('CharacterAdv', row)
            char = self.characters.setdefault(row['characterId'], {
                'id': row['characterId'], 'name': row.get('name', row['characterId']),
                'is_playable': False, 'speaker_names': [], 'speaker_patterns': [],
                'order': 0, 'source_record_ids': [],
            })
            char['speaker_names'].append(row['name'])
            if row.get('regexp'):
                char['speaker_patterns'].append(row['regexp'])
            char['source_record_ids'].append(sid)
        for cid, char in self.characters.items():
            self.groups['character:' + cid] = {
                'id': 'character:' + cid, 'kind': 'character', 'title': char['name'],
                'title_language': 'ja', 'parent_id': None, 'order': char['order'],
                'character_ids': [cid], 'image_asset_id': None, 'conditions': {},
                'source_record_id': char['source_record_ids'][0],
            }
        for table, kind in [('MainStoryPart', 'main_part'), ('MainStoryChapter', 'main_chapter'),
                            ('StoryEvent', 'event'), ('StoryGroup', 'story_group'),
                            ('ProduceGroup', 'produce_mode'), ('IdolCard', 'idol_card'),
                            ('SupportCard', 'support_card')]:
            for row in self.rows(table):
                chars = row.get('characterIds', []) or ([row['characterId']] if row.get('characterId') else [])
                parent = None
                if table == 'MainStoryChapter':
                    parent = 'MainStoryPart:' + row['mainStoryPartId']
                elif table == 'IdolCard' and chars:
                    parent = 'character:' + chars[0]
                gid = self.new_group(table, row, kind, parent, chars)
                if table == 'ProduceGroup':
                    self.modes_by_type[row['type']].add(gid)
                    for pid in row.get('produceIds', []):
                        self.modes_by_produce[pid].add(gid)
        for row in self.rows('MainStoryChapter'):
            gid = 'StoryGroup:' + row['mainStoryGroupId']
            if gid in self.groups:
                self.groups[gid]['parent_id'] = 'MainStoryChapter:' + row['id']
            else:
                self.warn('missing_group', group_id=gid)
        # Main-story event groups can be subsets of the chapter's canonical group.
        story_groups = {r['id']: r for r in self.rows('StoryGroup')}
        chapters = self.rows('MainStoryChapter')
        for row in self.rows('StoryGroup'):
            if row.get('storyType') != 'StoryType_Main' or not row.get('storyIds'):
                continue
            matches = [c for c in chapters if c['mainStoryGroupId'] in story_groups
                       and set(row['storyIds']) <= set(story_groups[c['mainStoryGroupId']]['storyIds'])]
            if len(matches) == 1:
                group = self.groups['StoryGroup:' + row['id']]
                if group['parent_id'] is None:
                    group['parent_id'] = 'MainStoryChapter:' + matches[0]['id']
                    group['parent_basis'] = 'story_id_subset'
        for row in self.rows('StoryEvent'):
            gid = 'StoryGroup:' + row.get('storyGroupId', '')
            if gid in self.groups:
                if self.groups[gid]['parent_id'] is None:
                    self.groups[gid]['parent_id'] = 'StoryEvent:' + row['id']
                elif row.get('storyEventType') == 'StoryEventType_MainStory':
                    self.groups['StoryEvent:' + row['id']]['parent_id'] = self.groups[gid]['parent_id']
        for row in self.rows('StoryGroup'):
            if row.get('characterId') and row['storyType'] == 'StoryType_DearnessStory':
                self.groups['StoryGroup:' + row['id']]['parent_id'] = 'character:' + row['characterId']

    def classify(self, table, row):
        if table == 'Story':
            # Some interludes also have a Birthday entry for the commu list.
            # Require the same character and an explicit ExtraDearnessStory source.
            if (row.get('type') == 'StoryType_Birthday'
                    and (row.get('characterId'), row.get('advAssetId')) in self.extra_dearness_scripts):
                return 'character.dearness'
            # The shared AprilFool source enum also contains anniversary campaigns.
            if 'anniversary' in row.get('id', '') and row.get('type') == 'StoryType_AprilFool':
                return 'event.campaign'
            return STORY_TYPES.get(row.get('type', '').removeprefix('StoryType_'), 'other.unclassified')
        if table == 'ProduceStory':
            return PRODUCE_TYPES.get(row.get('type', '').removeprefix('ProduceStoryType_'), 'other.unclassified')
        if table == 'CharacterDearnessLevel':
            return 'character.dearness'
        if table in ('ProduceLive', 'ProduceGroupLiveCommon'):
            return 'character.live'
        if table == 'Tutorial':
            return 'other.tutorial'
        if table == 'ProduceCharacterAdv':
            return 'character.training_stage'
        if table in ('ProduceAdv', 'ProduceSplitAdv'):
            return 'character.training_stage' if row.get('targetCharacterId') else 'other.training_shared'
        return {'ProduceStepTransition': 'character.training_transition',
                'ProduceStepOpenLessonMotion': 'character.training_lesson',
                'ProduceWeekMotion': 'character.training_week'}.get(table, 'other.unclassified')

    def entry(self, table, row, path, asset):
        sid = self.register(table, row)
        field = '/'.join(map(str, path))
        eid = sid + '/' + field
        category = self.classify(table, row)
        chars = set(row.get('characterIds', []))
        chars.update(row.get('unitCharacterIds', []))
        chars.update(row.get('unitLiveThumbnailAssetCharacterIds', []))
        chars.update(row[k] for k in ['characterId', 'targetCharacterId'] if row.get(k))
        modes = set(self.modes_by_type.get(row.get('produceType'), set()))
        if row.get('produceGroupId'):
            modes.add('ProduceGroup:' + row['produceGroupId'])
        for pid in row.get('produceIds', []):
            modes.update(self.modes_by_produce[pid])
        title = row.get('title') or None
        title_source = 'source' if title else 'asset_id'
        if not title and table == 'CharacterDearnessLevel':
            title = f"第{row['dearnessLevel']}話"
            title_source = 'generated'
        data = {
            'id': eid, 'script_id': asset, 'title': title or asset,
            'title_language': 'ja' if title else None, 'title_source': title_source,
            'category_id': category, 'classification_basis': 'source_type' if category != 'other.unclassified' else 'fallback',
            'character_ids': sorted(chars), 'inferred_character_ids': [],
            'idol_card_ids': [], 'support_card_ids': [], 'produce_mode_ids': sorted(modes),
            'group_ids': [], 'order': order_value(row),
            'conditions': conditions(row),
            'hints': row.get('produceEventHintProduceConditionDescriptions', []) or
                     ([row['produceConditionDescription']] if row.get('produceConditionDescription') else []),
            'previous_entry_id': 'Story:' + row['previousStoryId'] + '/advAssetId' if row.get('previousStoryId') else None,
            'source_type': row.get('type'), 'source_record_id': sid, 'source_field': field,
            'context': {label: row[k] for k, label in CONTEXT_NAMES.items() if k in row},
            'voice_bindings': [{'source_field': k, 'asset_id': v} for k, v in row.items()
                               if k.startswith('voiceAssetId') and isinstance(v, str) and v],
        }
        if path[0] in ('beforeAdvAssetId', 'afterAdvAssetId'):
            data['context']['live_phase'] = 'before' if path[0] == 'beforeAdvAssetId' else 'after'
        if table == 'Story' and row.get('type') == 'StoryType_Birthday' and category == 'character.dearness':
            data['classification_basis'] = 'shared_script'
        self.entries[eid] = data
        self.by_script[asset].append(data)
        script = self.script(asset)
        script['source_record_ids'].append(sid)
        if category == 'other.unclassified' and table not in ('AssetDownload', 'ProduceStory'):
            self.warn('unmapped_script_source', entry_id=eid)
        return data

    def collect_scripts(self):
        for table, rows in self.master.adv_tables():
            if table == 'PhotoBackground':
                continue
            self.rows(table)
            for row in rows:
                for path, asset in literal_refs(row):
                    if table == 'AssetDownload':
                        asset = asset.removesuffix('.txt')
                        sid = self.register(table, row)
                        self.script(asset)['source_record_ids'].append(sid)
                        continue
                    self.entry(table, row, path, asset)
        # AssetDownload-only references and CSV-only scripts get the same entry shape.
        csvs, self.csv_paths = read_csvs(self.stories)
        for asset, csv_info in csvs.items():
            script = self.script(asset)
            script.update(csv_info)
            if not script['source_record_ids']:
                script['metadata_status'] = 'unlinked_masterdata'
        for asset, script in list(self.scripts.items()):
            if asset in self.by_script:
                continue
            eid = 'script:' + asset
            source = script['source_record_ids'][0] if script['source_record_ids'] else None
            self.entries[eid] = {
                'id': eid, 'script_id': asset, 'title': asset, 'title_language': None,
                'title_source': 'asset_id', 'category_id': 'other.unclassified',
                'classification_basis': 'fallback', 'character_ids': [], 'inferred_character_ids': [],
                'idol_card_ids': [], 'support_card_ids': [], 'produce_mode_ids': [], 'group_ids': [],
                'order': 0, 'conditions': {}, 'hints': [], 'previous_entry_id': None,
                'source_type': None, 'source_record_id': source, 'source_field': 'id' if source else None,
                'context': {}, 'voice_bindings': [],
            }
            self.by_script[asset].append(self.entries[eid])

    def membership(self, entry, gid, sid, field, position=None, category=None):
        if gid not in self.groups:
            self.warn('missing_group', entry_id=entry['id'], group_id=gid)
            return
        entry['group_ids'].append(gid)
        entry['character_ids'].extend(self.groups[gid]['character_ids'])
        group_kind = self.groups[gid]['kind']
        target = {'idol_card': 'idol_card_ids', 'support_card': 'support_card_ids',
                  'produce_mode': 'produce_mode_ids'}.get(group_kind)
        if target:
            entry[target].append(gid)
        self.memberships.append({'entry_id': entry['id'], 'group_id': gid, 'position': position,
                                 'source_record_id': sid, 'source_field': field})
        if category:
            self.category_hints[entry['id']].add(category)

    def link_list(self, table, row, field, target, gid, category=None):
        sid = self.register(table, row)
        values = row.get(field, [])
        if isinstance(values, str):
            values = [values] if values else []
        for position, value in enumerate(values):
            eid = target + ':' + value + '/advAssetId'
            if eid not in self.entries:
                self.warn('dangling_story_reference', source_record_id=sid, source_field=field, target_id=eid)
                continue
            self.membership(self.entries[eid], gid, sid, field, position, category)

    def link_relations(self):
        for table, category in [('IdolCard', 'character.idol_card'), ('SupportCard', 'support_card.story')]:
            for row in self.rows(table):
                self.link_list(table, row, 'produceStoryIds', 'ProduceStory', table + ':' + row['id'], category)
        story_groups = {r['id']: r for r in self.rows('StoryGroup')}
        for row in self.rows('StoryEvent'):
            group = story_groups.get(row.get('storyGroupId'))
            if group:
                self.link_list('StoryGroup', group, 'storyIds', 'Story', 'StoryEvent:' + row['id'])
        for row in self.rows('Character'):
            self.link_list('Character', row, 'otherStoryIds', 'Story', 'character:' + row['id'])
        for row in self.rows('StoryGroup'):
            gid = 'StoryGroup:' + row['id']
            self.link_list('StoryGroup', row, 'storyIds', 'Story', gid)
        # Build indexes once; no repeated full-table scans per group.
        dear_by_character = defaultdict(list)
        for row in self.rows('CharacterDearnessLevel'):
            sid = self.register('CharacterDearnessLevel', row)
            eid = sid + '/advAssetId'
            if eid in self.entries:
                dear_by_character[row['characterId']].append((row, self.entries[eid]))
        for row in self.rows('StoryGroup'):
            if row.get('storyType') != 'StoryType_DearnessStory':
                continue
            for level, entry in dear_by_character[row.get('characterId')]:
                if row['dearnessLevelMin'] <= level['dearnessLevel'] <= row['dearnessLevelMax']:
                    self.membership(entry, 'StoryGroup:' + row['id'], 'StoryGroup:' + row['id'],
                                    'dearnessLevelMin/dearnessLevelMax', level['dearnessLevel'])
        for row in self.rows('CharacterProduceStory'):
            sid = self.register('CharacterProduceStory', row)
            for field, category in RELATION_CATEGORIES.items():
                gid = 'ProduceGroup:' + row['produceGroupId']
                self.link_list('CharacterProduceStory', row, field, 'ProduceStory', gid, category)
                for value in row.get(field, []):
                    eid = 'ProduceStory:' + value + '/advAssetId'
                    if eid in self.entries:
                        self.membership(self.entries[eid], 'character:' + row['characterId'], sid, field)
        # Group id is a family key, not a unique source key.
        for row in self.rows('ProduceStoryGroup'):
            sid = self.register('ProduceStoryGroup', row)
            family = 'produce_story_family:' + row['id']
            if family not in self.groups:
                self.groups[family] = {
                    'id': family, 'kind': 'produce_story_family', 'title': row['id'],
                    'title_language': None, 'parent_id': None, 'order': 0,
                    'character_ids': [], 'image_asset_id': None, 'conditions': {}, 'source_record_id': sid,
                }
            self.link_list('ProduceStoryGroup', row, 'produceStoryId', 'ProduceStory', family)
            self.link_list('ProduceStoryGroup', row, 'produceStoryId', 'ProduceStory', 'character:' + row['characterId'])
        self.link_event_branches()
        for entry in self.entries.values():
            for gid in list(entry['produce_mode_ids']):
                self.membership(entry, gid, entry['source_record_id'], 'produce_context')
            for cid in set(entry['character_ids']):
                if 'character:' + cid not in entry['group_ids']:
                    self.membership(entry, 'character:' + cid, entry['source_record_id'], 'character_context')

    def link_event_branches(self):
        """Follow explicit event choices; never infer continuations from filenames."""
        details = {row['id']: row for row in self.rows('ProduceStepEventDetail')}
        suggestions = {row['id']: row for row in self.rows('ProduceStepEventSuggestion')}
        edges = []
        for detail in details.values():
            parent = self.entries.get('ProduceStory:' + detail.get('produceStoryId', '') + '/advAssetId')
            if not parent:
                continue
            for ident in detail.get('produceStepEventSuggestionIds', []):
                choice = suggestions.get(ident, {})
                for field in ('stepId', 'successStepId', 'failStepId'):
                    target = details.get(choice.get(field))
                    child = self.entries.get('ProduceStory:' + target.get('produceStoryId', '') + '/advAssetId') if target else None
                    if child and child['category_id'] == parent['category_id'] and child['category_id'] in ('character.training_activity', 'character.training_business', 'character.training_school'):
                        edges.append((parent, child, choice, field))
        changed = True
        while changed:
            changed = False
            for parent, child, choice, field in edges:
                for gid in sorted(set(parent['produce_mode_ids']) - set(child['produce_mode_ids'])):
                    self.membership(child, gid, self.register('ProduceStepEventSuggestion', choice), field)
                    changed = True

    def classify_shared_training(self):
        """Shared by explicit role references, not by a roster-size threshold."""
        for entries in self.by_script.values():
            training = [e for e in entries if e['category_id'].startswith('character.training_')]
            if not training:
                continue
            chars = sorted({cid for e in training for cid in e['character_ids']})
            if len(chars) < 2:
                continue
            for entry in training:
                entry['context']['original_category_id'] = entry['category_id']
                entry['context']['shared_character_ids'] = chars
                entry['category_id'] = 'other.training_shared'
                entry['classification_basis'] = 'shared_script' if len(training) > 1 else 'explicit_relation'

    def refine(self):
        for entry in self.entries.values():
            hints = self.category_hints[entry['id']]
            if entry['category_id'] == 'other.unclassified' and len(hints) == 1:
                entry['category_id'] = next(iter(hints))
                entry['classification_basis'] = 'explicit_relation'
            if len(hints) > 1:
                self.warn('multiple_category_hints', entry_id=entry['id'], categories=sorted(hints))
        for asset, entries in self.by_script.items():
            categories = {e['category_id'] for e in entries if e['category_id'] != 'other.unclassified'}
            for entry in entries:
                shared_category = next(iter(categories)) if len(categories) == 1 else None
                if categories == {'character.dearness', 'character.training_stage'}:
                    shared_category = 'character.dearness'
                if entry['category_id'] == 'other.unclassified' and shared_category:
                    entry['category_id'] = shared_category
                    entry['classification_basis'] = 'shared_script'
                # Source IDs and filenames are only evidence for suggestions, never explicit ownership.
                tokens = set(re.split(r'[_\-]', asset))
                sid = entry['source_record_id']
                if sid:
                    tokens.update(re.split(r'[_\-]', str(self.sources[sid]['data'].get('id', ''))))
                entry['inferred_character_ids'] = sorted((tokens & self.characters.keys()) - set(entry['character_ids']))
                if entry['category_id'] == 'other.unclassified':
                    category = None
                    if asset.startswith('adv_tutorial_'):
                        category = 'other.tutorial'
                    elif asset.startswith('adv_event_highscore_'):
                        category = 'event.high_score'
                    elif asset.startswith('adv_tower-'):
                        category = 'other.tower'
                    elif asset.startswith('adv_gasha_'):
                        category = 'other.gacha'
                    elif asset.startswith('adv_pevent_') and '_sales_' in asset:
                        category = 'character.training_business'
                    elif asset.startswith(('adv_pstep_', 'adv_pweek_', 'adv_produce-lesson_')):
                        category = 'other.training_shared'
                    if category:
                        entry['category_id'] = category
                        entry['classification_basis'] = 'filename_hint'
                if entry['category_id'] == 'other.unclassified':
                    self.warn('unclassified_entry', entry_id=entry['id'])
        self.classify_shared_training()
        for entry in self.entries.values():
            for key in ['character_ids', 'inferred_character_ids', 'idol_card_ids', 'support_card_ids', 'produce_mode_ids', 'group_ids']:
                entry[key] = sorted(set(entry[key]))
        for group in self.groups.values():
            group.setdefault('metadata', {})
            group.setdefault('parent_basis', 'explicit' if group['parent_id'] else None)
        for asset, script in self.scripts.items():
            entries = self.by_script[asset]
            script['entry_ids'] = sorted(e['id'] for e in entries)
            script['source_record_ids'] = sorted(set(script['source_record_ids']))
            script['category_ids'] = sorted({e['category_id'] for e in entries})
            script['character_ids'] = sorted({c for e in entries for c in e['character_ids']})
            script['inferred_character_ids'] = sorted({c for e in entries for c in e['inferred_character_ids']} - set(script['character_ids']))
            if script['text_status'] == 'missing':
                self.warn('missing_csv', script_id=asset)
            if script['metadata_status'] == 'unlinked_masterdata':
                self.warn('unlinked_masterdata_script', script_id=asset)

    def build(self):
        self.prepare_entities()
        self.collect_scripts()
        self.link_relations()
        self.refine()
        categories = []
        for cid, label in {**ROOTS, **LEAVES}.items():
            matching = [e for e in self.entries.values() if e['category_id'] == cid or e['category_id'].startswith(cid + '.')]
            script_ids = {e['script_id'] for e in matching}
            categories.append({'id': cid, 'name': label, 'parent_id': cid.split('.')[0] if '.' in cid else None,
                               'entry_count': len(matching), 'script_count': len(script_ids),
                               'scripts_with_text': sum(self.scripts[s]['text_status'] == 'present' for s in script_ids)})
        conditions_by_id = defaultdict(list)
        for row in self.master.table('ConditionSet'):
            conditions_by_id[row['id']].append(row)
        for key in conditions_by_id:
            conditions_by_id[key].sort(key=canonical)
        memberships = sorted({canonical(r): r for r in self.memberships}.values(), key=lambda r: (
            r['group_id'], r['position'] is None, r['position'] or 0, r['entry_id'], r['source_field']))
        result = {
            'schema_version': '2.0.0', 'generator_version': __version__,
            'sources': {'masterdata': self.master.manifest(), 'stories': self.stories.manifest()},
            'categories': categories, 'characters': sorted(self.characters.values(), key=lambda r: (r['order'], r['id'])),
            'groups': sorted(self.groups.values(), key=lambda r: (r['order'], r['id'])),
            'entries': sorted(self.entries.values(), key=lambda r: (r['category_id'], r['order'], r['id'])),
            'scripts': sorted(self.scripts.values(), key=lambda r: r['id']),
            'memberships': memberships,
            'condition_sets': dict(sorted(conditions_by_id.items())),
            'source_records': sorted(self.sources.values(), key=lambda r: r['id']),
            'diagnostics': sorted(self.diagnostics, key=canonical),
            'stats': {'entry_count': len(self.entries), 'script_count': len(self.scripts),
                      'group_count': len(self.groups), 'character_count': len(self.characters),
                      'text_status_counts': dict(sorted(Counter(s['text_status'] for s in self.scripts.values()).items())),
                      'metadata_status_counts': dict(sorted(Counter(s['metadata_status'] for s in self.scripts.values()).items())),
                      'diagnostic_counts': dict(sorted(Counter(d['code'] for d in self.diagnostics).items()))},
        }
        validate_catalog(result)
        if self.csv_paths != sorted((self.stories.root / 'CSV').rglob('*.csv')):
            raise ValueError('CSV file list changed during build')
        self.master.verify()
        self.stories.verify()
        return result


def validate_catalog(catalog):
    def keyed(name):
        rows = catalog[name]
        result = {r['id']: r for r in rows}
        if len(result) != len(rows):
            raise ValueError(f'Duplicate IDs in {name}')
        return result
    entries, scripts, groups, sources, characters, categories = [keyed(k) for k in (
        'entries', 'scripts', 'groups', 'source_records', 'characters', 'categories')]
    for entry in entries.values():
        if entry['script_id'] not in scripts or entry['category_id'] not in categories:
            raise ValueError(f'Invalid entry reference: {entry["id"]}')
        if entry['source_record_id'] and entry['source_record_id'] not in sources:
            raise ValueError('Unknown source record')
        for cid in entry['character_ids'] + entry['inferred_character_ids']:
            if cid not in characters:
                raise ValueError(f'Unknown character: {cid}')
        if not set(entry['group_ids']) <= groups.keys():
            raise ValueError('Unknown entry group')
        for key, kind in [('idol_card_ids', 'idol_card'), ('support_card_ids', 'support_card'),
                          ('produce_mode_ids', 'produce_mode')]:
            if any(g not in groups or groups[g]['kind'] != kind for g in entry[key]):
                raise ValueError(f'Invalid {key} reference')
        if entry['previous_entry_id'] and entry['previous_entry_id'] not in entries:
            raise ValueError('Unknown previous story')
    for group in groups.values():
        if group['source_record_id'] not in sources:
            raise ValueError('Unknown group source')
        if not set(group['character_ids']) <= characters.keys():
            raise ValueError('Unknown group character')
        current = group
        seen = set()
        while current['parent_id']:
            if current['id'] in seen or current['parent_id'] not in groups:
                raise ValueError(f'Invalid group ancestry: {group["id"]}')
            seen.add(current['id'])
            current = groups[current['parent_id']]
    for record in [*entries.values(), *groups.values()]:
        for condition in record['conditions'].values():
            if condition not in catalog['condition_sets']:
                raise ValueError(f'Undefined condition set: {condition}')
    for script in scripts.values():
        if not set(script['source_record_ids']) <= sources.keys():
            raise ValueError('Invalid script source record')
        if not script['entry_ids'] or any(e not in entries or entries[e]['script_id'] != script['id'] for e in script['entry_ids']):
            raise ValueError('Invalid script entry list')
    for membership in catalog['memberships']:
        if membership['entry_id'] not in entries or membership['group_id'] not in groups:
            raise ValueError('Invalid membership')
        if membership['source_record_id'] and membership['source_record_id'] not in sources:
            raise ValueError('Invalid membership source')
    for source in sources.values():
        if source['table'] in ('Story', 'ProduceStory') and source['data'].get('advAssetId'):
            if source['id'] + '/advAssetId' not in entries:
                raise ValueError('Source story was omitted')
