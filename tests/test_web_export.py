import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from campus_story_index.web_assets import decode_header, image_requests, display_size
from campus_story_index.web_export import build, canonical_directory_entries
from campus_story_index.io import atomic_write


class WebExportTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        entry = {'id':'entry/1','script_id':'adv_test','title':'第一话','category_id':'main.chapter',
                 'character_ids':[], 'order':1,'group_ids':[], 'conditions':{},'context':{}}
        catalog = {'characters':[], 'source_records':[], 'groups':[],
                   'categories':[{'id':'main','name':'主线剧情','parent_id':None},
                                 {'id':'main.chapter','name':'章节','parent_id':'main'}],
                   'entries':[entry,{**entry,'id':'entry/2','context':{'variant':2}}],
                   'scripts':[{'id':'adv_test','csv_path':'CSV/adv_test.csv','text_status':'present',
                               'text_row_count':2,'translated_row_count':0}]}
        atomic_write(root/'catalog.json',catalog)
        atomic_write(root/'assets.json',{'images':[]})
        atomic_write(root/'voices.json',{'sources':{'catalog_sha256':hashlib.sha256((root/'catalog.json').read_bytes()).hexdigest()},
            'scripts':[{'script_id':'adv_test','voice_event_count':1}]})
        (root/'CharacterDetail.yaml').write_text('[]')
        (root/'CharacterColor.yaml').write_text('[]')
        return root, (root/'catalog.json',root,root/'assets.json',root/'voices.json',root/'output')

    def test_preserve_variants_and_deterministic_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root,args=self.fixture(directory)
            result=build(*args); before=(root/'output/manifest.json').read_bytes()
            folder=root/'output/builds'/result['build_id']
            chapter=json.loads((folder/'chapters/adv_test.json').read_text())
            self.assertEqual([e['id'] for e in chapter['entries']],['entry/1','entry/2'])
            self.assertEqual(chapter['voice_event_count'],1)
            self.assertEqual(chapter['entries'][0]['group_title'],'章节')
            self.assertEqual((folder/'chapters/adv_test.json').stat().st_mode & 0o777,0o644)
            self.assertEqual(folder.stat().st_mode & 0o777,0o755)
            build(*args)
            self.assertEqual(before,(root/'output/manifest.json').read_bytes())

    def test_changed_input_does_not_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            root,args=self.fixture(directory); build(*args)
            before=(root/'output/manifest.json').read_bytes()
            def change(path,value):
                atomic_write(path,value)
                (root/'CharacterColor.yaml').write_text('[{}]')
            with patch('campus_story_index.web_export.atomic_write',side_effect=change):
                with self.assertRaisesRegex(ValueError,'Input changed'): build(*args)
            self.assertEqual(before,(root/'output/manifest.json').read_bytes())

    def test_header_rejects_invalid_and_preserves_plain_unity(self):
        self.assertEqual(decode_header(b'UnityFS\0example','sample'),b'UnityFS\0example')
        with self.assertRaises(ValueError): decode_header(b'tiny','sample')
        with self.assertRaises(ValueError): decode_header(bytes(256),'sample')

    def test_rejects_stale_voice_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root,args=self.fixture(directory)
            with (root/'catalog.json').open('a') as file: file.write(' ')
            with self.assertRaisesRegex(ValueError,'different story catalog'): build(*args)

    def test_full_card_stages_and_missing_variant(self):
        with tempfile.TemporaryDirectory() as directory:
            root, args = self.fixture(directory)
            catalog = json.loads((root/'catalog.json').read_text())
            catalog['groups'] = [{'id': 'card', 'kind': 'idol_card', 'image_asset_id': 'cidol-test', 'title': '卡牌', 'order': 0}]
            for entry in catalog['entries']: entry['group_ids'] = ['card']
            atomic_write(root/'catalog.json', catalog)
            voices = json.loads((root/'voices.json').read_text())
            voices['sources']['catalog_sha256'] = hashlib.sha256((root/'catalog.json').read_bytes()).hexdigest()
            atomic_write(root/'voices.json', voices)
            for count in (2, 1):
                atomic_write(root/'assets.json', {'images': [{'name': f'img_general_cidol-test_{i}-full', 'path': f'images/stage-{i}.webp'} for i in range(count)]})
                result = build(*args)
                rows = json.loads((root/'output/builds'/result['build_id']/'lists/main.json').read_text())
                self.assertEqual(len(rows[0]['group_images']), count)
                self.assertEqual(rows[0]['group_images'][0]['aspect_ratio'], 9 / 16)
                self.assertEqual(rows[0]['group_image'], '/assets/images/stage-0.webp')

    def test_main_chapter_cover_and_readable_number(self):
        with tempfile.TemporaryDirectory() as directory:
            root, args = self.fixture(directory)
            catalog = json.loads((root/'catalog.json').read_text())
            catalog['groups'] = [
                {'id': 'part', 'kind': 'main_part', 'title': '1部', 'order': 1},
                {'id': 'chapter', 'kind': 'main_chapter', 'title': '1章', 'order': 1, 'parent_id': 'part', 'source_record_id': 'MainStoryChapter:test'},
                {'id': 'group', 'kind': 'story_group', 'title': 'main_story_group-01-01', 'order': 1, 'parent_id': 'chapter'}]
            catalog['source_records'] = [{'id': 'MainStoryChapter:test', 'data': {'storyAssetId': '01-01'}}]
            for entry in catalog['entries']: entry['group_ids'] = ['group']
            atomic_write(root/'catalog.json', catalog)
            voices = json.loads((root/'voices.json').read_text())
            voices['sources']['catalog_sha256'] = hashlib.sha256((root/'catalog.json').read_bytes()).hexdigest()
            atomic_write(root/'voices.json', voices)
            atomic_write(root/'assets.json', {'images': [{'name': 'img_general_commu_chapter-thumb_01-01', 'path': 'images/chapter.webp'}]})
            result = build(*args)
            rows = json.loads((root/'output/builds'/result['build_id']/'lists/main.json').read_text())
            self.assertEqual(rows[0]['group_title'], '1部 / 1章')
            self.assertEqual(rows[0]['group_image'], '/assets/images/chapter.webp')

    def test_event_cover_prefers_larger_asset_and_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root, args = self.fixture(directory)
            catalog = json.loads((root/'catalog.json').read_text())
            catalog['groups'] = [{'id': 'parent', 'kind': 'event', 'title': '活动', 'order': 1}, {'id': 'event', 'kind': 'story_group', 'title': '活动', 'order': 1, 'parent_id': 'parent', 'image_asset_id': 'img_event-story-banner'}]
            for entry in catalog['entries']: entry['group_ids'] = ['event']
            atomic_write(root/'catalog.json', catalog)
            voices = json.loads((root/'voices.json').read_text())
            voices['sources']['catalog_sha256'] = hashlib.sha256((root/'catalog.json').read_bytes()).hexdigest()
            atomic_write(root/'voices.json', voices)
            small = {'name': 'img_event-story-banner', 'path': 'images/small.webp', 'width': 512, 'height': 128}
            large = {'name': 'img_event-banner', 'path': 'images/large.webp', 'width': 1024, 'height': 256}
            for images, expected in [([small, large], 'large'), ([small], 'small'), ([small, {**large, 'width': 128, 'height': 32}], 'small')]:
                atomic_write(root/'assets.json', {'images': images})
                result = build(*args)
                rows = json.loads((root/'output/builds'/result['build_id']/'lists/main.json').read_text())
                self.assertEqual(rows[0]['group_title'], '活动')
                self.assertEqual(rows[0]['group_image'], f'/assets/images/{expected}.webp')
                self.assertEqual(rows[0]['group_images'][0]['aspect_ratio'], 4)

    def test_event_banner_ratio_excludes_other_banner_types(self):
        self.assertEqual(display_size('img_general_event_story_event-story-001-banner', (1024, 256)), (1024, 341))
        for suffix in ['story-banner', 'reward-banner', 'rev-banner']:
            self.assertIsNone(display_size('img_general_event_test-' + suffix, (512, 128)))

    def test_event_replay_superset_wins_without_title_merging(self):
        groups = {key: {'kind': 'story_group'} for key in ('live', 'replay', 'distinct')}
        rows = []
        for group, scripts in [('live', ['a', 'b']), ('replay', ['intro', 'a', 'b', 'end']), ('distinct', ['c'])]:
            for order, script in enumerate(scripts):
                rows.append({'id': group + script, 'script_id': script, 'category_id': 'event.tour' if group == 'live' else 'event.april_fool', 'group_ids': [group], 'order': order})
        rows.append({'id': 'startup', 'script_id': 'intro', 'category_id': 'event.april_fool', 'group_ids': [], 'order': 0})
        chosen, sources = canonical_directory_entries(rows, groups)
        self.assertEqual(chosen['a'], 'replaya')
        self.assertEqual(chosen['intro'], 'replayintro')
        self.assertEqual(chosen['c'], 'distinctc')
        self.assertEqual(sources['a'], ['livea', 'replaya'])
        self.assertEqual(len(chosen), 5)

    def test_dearness_prefers_step_over_duplicate_character_entry(self):
        groups = {'step': {'kind': 'story_group'}, 'character:x': {'kind': 'character'}}
        base = {'script_id': 'adv_dear_x_001', 'category_id': 'character.dearness', 'order': 1}
        entries = [{**base, 'id': 'raw', 'group_ids': []}, {**base, 'id': 'character', 'group_ids': ['character:x']}, {**base, 'id': 'step', 'group_ids': ['step', 'character:x']}]
        chosen, sources = canonical_directory_entries(entries, groups)
        self.assertEqual(chosen[base['script_id']], 'step')
        self.assertEqual(len(sources[base['script_id']]), 3)

    def test_toolkit_card_dimensions(self):
        self.assertEqual(display_size('img_general_cidol-test_0-full'), (1440, 2560))
        self.assertEqual(display_size('img_general_csprt-test_full'), (2560, 1440))
        self.assertIsNone(display_size('img_chr_test_00-full'))

    def test_image_plan_uses_exact_card_variants(self):
        result=image_requests({'characters':[{'id':'test','is_playable':True}],
            'groups':[{'kind':'idol_card','image_asset_id':'cidol-test'},
                      {'kind':'support_card','image_asset_id':'csprt-test'}]})
        self.assertIn('img_general_cidol-test_0-full',result)
        self.assertIn('img_general_csprt-test_full',result)
        self.assertIn('img_chr_test_00-full',result)
        self.assertIn('img_general_cidol-test_1-full',result)


    def test_support_facets_include_all_card_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            root, args = self.fixture(directory)
            catalog = json.loads((root/'catalog.json').read_text())
            catalog['categories'] = [{'id': 'support_card', 'name': '辅助卡', 'parent_id': None},
                {'id': 'support_card.story', 'name': '辅助卡剧情', 'parent_id': 'support_card'}]
            catalog['groups'] = [{'id': 'SupportCard:test', 'kind': 'support_card',
                'title': 'Test card', 'parent_id': None, 'source_record_id': 'SupportCard:test',
                'order': 1, 'image_asset_id': None}]
            catalog['source_records'] = [{'id': 'SupportCard:test', 'data': {
                'rarity': 'SupportCardRarity_Ssr', 'type': 'SupportCardType_Vocal',
                'characterIds': ['hski', 'ttmr'], 'viewStartTime': '1700000000000'}}]
            for entry in catalog['entries']:
                entry.update(category_id='support_card.story', group_ids=['SupportCard:test'], character_ids=['hski'])
            atomic_write(root/'catalog.json', catalog)
            voices = json.loads((root/'voices.json').read_text())
            voices['sources']['catalog_sha256'] = hashlib.sha256((root/'catalog.json').read_bytes()).hexdigest()
            atomic_write(root/'voices.json', voices)
            result = build(*args)
            rows = json.loads((root/'output/builds'/result['build_id']/'lists/support_card.json').read_text())
            self.assertEqual(rows[0]['support_rarity'], 'SSR')
            self.assertEqual(rows[0]['support_attribute'], 'Vocal')
            self.assertEqual(rows[0]['character_ids'], ['hski', 'ttmr'])
            self.assertEqual(rows[0]['release_at'], 1700000000000)
            self.assertIsNone(rows[0]['text_updated_at'])


    def test_pending_text_relinks_when_masterdata_arrives(self):
        with tempfile.TemporaryDirectory() as directory:
            root, args = self.fixture(directory)
            catalog = json.loads((root/'catalog.json').read_text())
            catalog['scripts'][0]['metadata_status'] = 'unlinked_masterdata'
            catalog['scripts'][0]['id'] = 'adv_csprt-3-9999_01'
            for entry in catalog['entries']:
                entry['script_id'] = 'adv_csprt-3-9999_01'
            atomic_write(root/'assets.json', {'images': [{'name': 'img_general_csprt-3-9999_full', 'path': 'images/future.webp'}]})
            def publish():
                atomic_write(root/'catalog.json', catalog)
                voices = json.loads((root/'voices.json').read_text())
                voices['sources']['catalog_sha256'] = hashlib.sha256((root/'catalog.json').read_bytes()).hexdigest()
                atomic_write(root/'voices.json', voices)
                info = build(*args)
                return json.loads((root/'output/builds'/info['build_id']/'updates.json').read_text())
            pending = publish()
            self.assertEqual(pending['pending_count'], 1)
            self.assertEqual(len(pending['items']), 1)  # source aliases do not duplicate the feed
            self.assertEqual(pending['items'][0]['title'], '名称待补全')
            self.assertEqual(pending['items'][0]['category_id'], 'support_card.story')
            self.assertEqual(pending['items'][0]['images'][0]['url'], '/assets/images/future.webp')
            self.assertEqual(pending['items'][0]['character_ids'], [])
            catalog['scripts'][0]['metadata_status'] = 'referenced'
            for entry in catalog['entries']:
                entry['source_type'] = None  # Valid masterdata tables need not contain a type field.
                entry['source_record_id'] = 'CharacterDearnessLevel:test'
            linked = publish()
            self.assertEqual(linked['pending_count'], 0)
            self.assertEqual(linked['items'][0]['title'], '第一话')
            catalog['scripts'][0]['text_status'] = 'empty'
            self.assertEqual(publish()['items'], [])


class ReleaseTimeTests(unittest.TestCase):
    def test_display_time_and_opening_bound(self):
        from campus_story_index.web_export import release_time
        conditions = {'open': [{'conditionType': 'ConditionType_TimeTerm',
            'conditionOperatorType': 'ConditionOperatorType_And',
            'beforeTime': '1700000000000', 'afterTime': '1800000000000'}]}
        self.assertEqual(release_time({'viewConditionSetId': 'open'}, conditions), 1700000000000)
        self.assertEqual(release_time({'viewStartTime': '1750000000000', 'viewConditionSetId': 'open'}, conditions), 1750000000000)
        self.assertIsNone(release_time({'viewStartTime': '0'}, conditions))
        conditions['open'].append({'conditionOperatorType': 'ConditionOperatorType_Or',
                                   'conditionType': 'ConditionType_MissionCompleted'})
        self.assertIsNone(release_time({'viewConditionSetId': 'open'}, conditions))

    def test_text_dates_use_pinned_revision(self):
        import os
        import subprocess
        from campus_story_index.web_export import text_update_times, text_changes
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args, **kwargs):
                return subprocess.check_output(['git', '-C', str(root), *args], text=True, **kwargs).strip()
            git('init', '-q')
            git('config', 'user.name', 'Test')
            git('config', 'user.email', 'test@example.invalid')
            (root/'CSV').mkdir()
            file = root/'CSV/adv_sample.csv'
            file.write_text('first')
            git('add', 'CSV')
            env = {**os.environ, 'GIT_AUTHOR_DATE': '2024-05-16T00:00:00+00:00', 'GIT_COMMITTER_DATE': '2024-05-16T00:00:00+00:00'}
            git('commit', '-qm', 'first', env=env)
            revision = git('rev-parse', 'HEAD')
            first = text_update_times(root, revision)
            self.assertEqual(text_changes(root, revision)['CSV/adv_sample.csv']['kind'], 'added')
            file.write_text('translation update')
            git('add', 'CSV')
            env.update(GIT_AUTHOR_DATE='2025-05-16T00:00:00+00:00', GIT_COMMITTER_DATE='2025-05-16T00:00:00+00:00')
            git('commit', '-qm', 'second', env=env)
            self.assertEqual(text_update_times(root, revision), first)
            self.assertEqual(text_changes(root, 'HEAD')['CSV/adv_sample.csv']['kind'], 'modified')
            self.assertEqual(text_changes(root, revision)['CSV/adv_sample.csv']['kind'], 'added')
            self.assertGreater(text_update_times(root, 'HEAD')['CSV/adv_sample.csv'], first['CSV/adv_sample.csv'])
            self.assertEqual(text_update_times(None, revision), {})

if __name__ == '__main__': unittest.main()
