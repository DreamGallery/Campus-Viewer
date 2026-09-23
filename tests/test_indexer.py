import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from campus_story_index.builder import CatalogBuilder, REQUIRED_TABLES, validate_catalog
from campus_story_index.io import Snapshot, atomic_write


class IndexerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.master = self.root / 'master'
        self.stories = self.root / 'stories'
        self.master.mkdir()
        (self.stories / 'CSV').mkdir(parents=True)
        for name in REQUIRED_TABLES:
            self.table(name, [])
        self.table('Character', [{'id': 'test', 'firstName': '試験', 'isPlayable': True}])
        self.table('Story', [self.story('story-1', 'adv_sample')])
        self.csv('adv_sample')

    def table(self, name, rows):
        (self.master / (name + '.yaml')).write_text(yaml.safe_dump(rows, allow_unicode=True))

    def csv(self, asset, texts=(('1', '試験', '原文', ''),), folder=''):
        directory = self.stories / 'CSV' / folder
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / (asset + '.csv')).open('w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['id', 'name', 'text', 'trans'])
            writer.writerows(texts)

    def story(self, sid, asset, **kw):
        return {'id': sid, 'advAssetId': asset, 'title': '話', 'type': 'StoryType_Main', **kw}

    def build(self):
        return CatalogBuilder(self.master, self.stories).build()

    def test_json_schema_contract(self):
        from jsonschema import Draft202012Validator
        schema = json.loads((Path(__file__).resolve().parents[1] / 'docs/story-index.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(self.build())

    def test_deterministic_and_five_roots(self):
        first = self.build()
        self.assertEqual(first, self.build())
        self.assertEqual({c['id'] for c in first['categories'] if c['parent_id'] is None},
                         {'main', 'character', 'support_card', 'event', 'other'})
        self.assertEqual(first['entries'][0]['category_id'], 'main.story')

    def test_shared_script_keeps_two_source_entries(self):
        self.table('ProduceStory', [{'id': 'alias', 'advAssetId': 'adv_sample', 'type': 'ProduceStoryType_Unknown'}])
        catalog = self.build()
        self.assertEqual(len(catalog['scripts']), 1)
        self.assertEqual(len(catalog['entries']), 2)
        alias = next(e for e in catalog['entries'] if e['id'].startswith('ProduceStory:'))
        self.assertEqual(alias['classification_basis'], 'shared_script')
        self.assertEqual(alias['category_id'], 'main.story')

    def test_birthday_alias_of_dearness_interlude(self):
        self.table('Character', [{'id': cid, 'firstName': cid, 'isPlayable': True}
                                 for cid in ('test', 'other')])
        self.table('Story', [
            self.story('interlude', 'adv_sample', type='StoryType_ExtraDearnessStory', characterId='test'),
            self.story('list-alias', 'adv_sample', type='StoryType_Birthday', characterId='test'),
            self.story('birthday', 'adv_birthday', type='StoryType_Birthday', characterId='test'),
            self.story('other-character', 'adv_sample', type='StoryType_Birthday', characterId='other'),
        ])
        entries = {e['source_record_id']: e for e in self.build()['entries']}
        alias = entries['Story:list-alias']
        self.assertEqual(alias['category_id'], 'character.dearness')
        self.assertEqual(alias['classification_basis'], 'shared_script')
        self.assertEqual(alias['source_type'], 'StoryType_Birthday')
        self.assertEqual(entries['Story:birthday']['category_id'], 'character.birthday')
        self.assertEqual(entries['Story:other-character']['category_id'], 'character.birthday')

    def test_unlisted_produce_story_is_not_lost(self):
        self.table('ProduceStory', [{'id': 'unlisted', 'advAssetId': 'adv_unlisted', 'type': 'ProduceStoryType_StepSchoolEvent'}])
        catalog = self.build()
        entry = next(e for e in catalog['entries'] if e['script_id'] == 'adv_unlisted')
        self.assertEqual(entry['category_id'], 'character.training_school')
        self.assertEqual(next(s for s in catalog['scripts'] if s['id'] == 'adv_unlisted')['text_status'], 'missing')

    def test_download_extension_and_background_exclusion(self):
        self.table('AssetDownload', [{'id': 'adv_sample.txt'}, {'id': 'adv_tutorial_only.txt'}])
        self.table('PhotoBackground', [{'id': 'photo', 'backgroundAssetId': 'adv_room'}])
        catalog = self.build()
        self.assertEqual({s['id'] for s in catalog['scripts']}, {'adv_sample', 'adv_tutorial_only'})

    def test_unlinked_masterdata_and_empty_status(self):
        self.csv('adv_orphan', [('info', 'adv_orphan.txt', '', ''), ('译者', '', '', '')])
        catalog = self.build()
        script = next(s for s in catalog['scripts'] if s['id'] == 'adv_orphan')
        self.assertEqual(script['metadata_status'], 'unlinked_masterdata')
        self.assertEqual(script['text_status'], 'empty')
        self.assertTrue(script['entry_ids'])

    def test_duplicate_csv_basename_fails(self):
        self.csv('adv_sample', folder='duplicate')
        with self.assertRaisesRegex(ValueError, 'Duplicate CSV'):
            self.build()

    def test_duplicate_primary_key_fails(self):
        self.table('Story', [self.story('same', 'adv_sample'), self.story('same', 'adv_different')])
        with self.assertRaisesRegex(ValueError, 'Duplicate source key'):
            self.build()

    def test_composite_key_keeps_character_variants(self):
        rows = [{'id': 'family', 'characterId': c, 'produceStoryId': 'p'} for c in ['test', 'second']]
        self.table('Character', [{'id': 'test'}, {'id': 'second'}])
        self.table('ProduceStory', [{'id': 'p', 'advAssetId': 'adv_sample', 'type': 'ProduceStoryType_Character'}])
        self.table('ProduceStoryGroup', rows)
        catalog = self.build()
        records = [r for r in catalog['source_records'] if r['table'] == 'ProduceStoryGroup']
        self.assertEqual(len(records), 2)
        entry = next(e for e in catalog['entries'] if e['id'].startswith('ProduceStory:'))
        self.assertEqual(entry['character_ids'], ['second', 'test'])

    def test_dynamic_context_keeps_voice_bindings_and_stable_identity(self):
        row = {'characterId': 'test', 'stepType': 'Lesson', 'number': 1,
               'advId': 'adv_lesson', 'voiceAssetId1': 'voice_1', 'voiceAssetId2': 'voice_2'}
        self.table('ProduceStepOpenLessonMotion', [row])
        first = next(e for e in self.build()['entries'] if e['script_id'] == 'adv_lesson')
        row.update(title='changed title', voiceAssetId1='voice_new')
        self.table('ProduceStepOpenLessonMotion', [row])
        second = next(e for e in self.build()['entries'] if e['script_id'] == 'adv_lesson')
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(len(first['voice_bindings']), 2)
        self.assertNotEqual(first['voice_bindings'], second['voice_bindings'])

    def test_translation_edit_does_not_change_source_text_hash(self):
        first = self.build()['scripts'][0]
        self.csv('adv_sample', [('1', '試験', '原文', '译文')])
        second = self.build()['scripts'][0]
        self.assertEqual(first['source_text_sha256'], second['source_text_sha256'])
        self.assertNotEqual(first['file_sha256'], second['file_sha256'])
        self.assertEqual(second['translated_row_count'], 1)

    def test_membership_preserves_list_order_and_card_context(self):
        self.table('ProduceStory', [{'id': key, 'advAssetId': 'adv_' + key, 'type': 'ProduceStoryType_IdolCard', 'order': order}
                                    for key, order in [('a', 10), ('b', 1)]])
        self.table('IdolCard', [{'id': 'card', 'characterId': 'test', 'name': '卡', 'produceStoryIds': ['b', 'a']}])
        catalog = self.build()
        memberships = [m for m in catalog['memberships'] if m['group_id'] == 'IdolCard:card']
        self.assertEqual([m['entry_id'] for m in memberships], ['ProduceStory:b/advAssetId', 'ProduceStory:a/advAssetId'])
        entry = next(e for e in catalog['entries'] if e['id'] == 'ProduceStory:a/advAssetId')
        self.assertEqual(entry['idol_card_ids'], ['IdolCard:card'])
        self.assertEqual(entry['character_ids'], ['test'])

    def test_conditions_and_main_subset_hierarchy(self):
        self.table('Story', [self.story('story-1', 'adv_sample', viewConditionSetId='cd', unlockConditionSetId='cd')])
        self.table('ConditionSet', [{'id': 'cd', 'number': 1}, {'id': 'cd', 'number': 2}])
        self.table('MainStoryPart', [{'id': 'part'}])
        self.table('MainStoryChapter', [{'id': 'chapter', 'mainStoryPartId': 'part', 'mainStoryGroupId': 'whole'}])
        self.table('StoryGroup', [{'id': x, 'storyType': 'StoryType_Main', 'storyIds': ['story-1']} for x in ['whole', 'subset']])
        catalog = self.build()
        self.assertEqual(len(catalog['condition_sets']['cd']), 2)
        self.assertEqual(catalog['entries'][0]['conditions'], {'visible_if': 'cd', 'unlocked_if': 'cd'})
        group = next(g for g in catalog['groups'] if g['id'] == 'StoryGroup:subset')
        self.assertEqual(group['parent_id'], 'MainStoryChapter:chapter')
        self.assertEqual(group['parent_basis'], 'story_id_subset')

    def test_unknown_table_is_kept_and_flagged(self):
        self.table('FutureStory', [{'id': 'new', 'advAssetId': 'adv_future'}])
        catalog = self.build()
        self.assertIn('adv_future', {s['id'] for s in catalog['scripts']})
        self.assertTrue(any(d['code'] == 'unmapped_script_source' for d in catalog['diagnostics']))

    def test_dangling_reference_reported(self):
        self.table('StoryGroup', [{'id': 'group', 'storyIds': ['absent']}])
        self.assertTrue(any(d['code'] == 'dangling_story_reference' for d in self.build()['diagnostics']))

    def test_empty_story_asset_fails_instead_of_omission(self):
        self.table('Story', [self.story('empty', '')])
        with self.assertRaisesRegex(ValueError, 'missing or invalid script'):
            self.build()

    def test_snapshot_change_is_detected(self):
        snapshot = Snapshot(self.master)
        snapshot.read('Story.yaml')
        self.table('Story', [])
        with self.assertRaisesRegex(ValueError, 'Input changed'):
            snapshot.verify()

    def test_atomic_write_failure_preserves_previous_file(self):
        output = self.root / 'index.json'
        atomic_write(output, {'old': True})
        with patch('campus_story_index.io.os.replace', side_effect=OSError('test')):
            with self.assertRaises(OSError):
                atomic_write(output, {'new': True})
        self.assertEqual(json.loads(output.read_text()), {'old': True})
        self.assertEqual(list(self.root.glob('.index.json*')), [])

    def test_group_cycle_rejected(self):
        catalog = self.build()
        catalog['groups'][0]['parent_id'] = catalog['groups'][0]['id']
        with self.assertRaisesRegex(ValueError, 'ancestry'):
            validate_catalog(catalog)


if __name__ == '__main__':
    unittest.main()


class EventBranchTests(unittest.TestCase):
    def test_explicit_choices_propagate_modes_and_terminate_cycles(self):
        builder=CatalogBuilder.__new__(CatalogBuilder)
        category='character.training_activity'
        def entry(name,modes):return {'id':name,'category_id':category,'produce_mode_ids':modes}
        builder.entries={'ProduceStory:a/advAssetId':entry('a',['first','nia']), 'ProduceStory:b/advAssetId':entry('b',[]), 'ProduceStory:c/advAssetId':entry('c',[])}
        tables={'ProduceStepEventDetail':[{'id':'a','produceStoryId':'a','produceStepEventSuggestionIds':['choice-a']},{'id':'b','produceStoryId':'b','produceStepEventSuggestionIds':['choice-b']}],
                'ProduceStepEventSuggestion':[{'id':'choice-a','successStepId':'b'},{'id':'choice-b','failStepId':'a'}]}
        builder.rows=lambda name:tables[name]
        builder.register=lambda table,row:table+':'+row['id']
        calls=[]
        def membership(child,gid,source,field):
            child['produce_mode_ids'].append(gid);calls.append((child['id'],source,field))
        builder.membership=membership
        builder.link_event_branches()
        self.assertEqual(builder.entries['ProduceStory:b/advAssetId']['produce_mode_ids'],['first','nia'])
        self.assertEqual(builder.entries['ProduceStory:c/advAssetId']['produce_mode_ids'],[])
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0][2],'successStepId')


class SharedTrainingTests(unittest.TestCase):
    def test_partial_roster_shared_script_moves_but_personal_and_cards_stay(self):
        builder=CatalogBuilder.__new__(CatalogBuilder)
        def entry(cat,chars):return {'category_id':cat,'character_ids':chars,'context':{},'classification_basis':'source_type'}
        school=[entry('character.training_school',['a']),entry('character.training_school',['b'])]
        personal=[entry('character.training_story',['a'])]
        card=[entry('character.idol_card',['a','b'])]
        unit=[entry('character.training_stage',['a','b'])]
        builder.by_script={'shared':school,'unique':personal,'card':card,'unit':unit}
        builder.classify_shared_training()
        self.assertEqual({e['category_id'] for e in school},{'other.training_shared'})
        self.assertEqual(school[0]['context']['shared_character_ids'],['a','b'])
        self.assertEqual(school[0]['context']['original_category_id'],'character.training_school')
        self.assertEqual(personal[0]['category_id'],'character.training_story')
        self.assertEqual(card[0]['category_id'],'character.idol_card')
        self.assertEqual(unit[0]['category_id'],'other.training_shared')
