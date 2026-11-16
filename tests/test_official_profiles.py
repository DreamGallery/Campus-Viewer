import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import requests

from campus_story_index.official_profiles import (
    INDEX_URL, ORIGIN, ProfilePage, fetch_profile, media_available, sync_profiles,
)


def page(slug='fresh', introduction='Official introduction'):
    return ProfilePage(f'''<div id="current_idol" data-current="{slug}">
        <p class="idol__serif-text">A &amp; B</p>
        <p class="idol-info__text {slug}">{introduction}</p>
        <a class="idol-info__voice-btn" data-voice="1"></a>
        <a class="idol-info__voice-btn" data-voice="2"></a></div>''')


class OfficialProfilesTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary)
        self.seed = self.root / 'seed.json'
        self.seed.write_text('{}')
        self.enterContext(patch('campus_story_index.official_profiles.SEED_PATH', self.seed))
        self.cache = self.root / 'cache/profiles.json'
        (self.root / 'Character.yaml').write_text(json.dumps([
            {'id': 'new', 'lastName': 'Fresh', 'firstName': 'Idol', 'isPlayable': True},
            {'id': 'waiting', 'lastName': 'Future', 'firstName': 'Idol', 'isPlayable': True}]))
        self.index = ProfilePage('''<div id="current_idol" data-current="saki"></div>
            <a class="other idol-nav__link" href="/idol/fresh/">
            <p class="idol-nav__thumb"><img src="/assets/img/idol/fresh/thumb.png"></p>
            <p class="idol-nav__name"> Fresh　<b>Idol</b> </p></a>''')
        self.entry = self.index.roster['FreshIdol']

    def test_discovers_new_character_by_name_and_preserves_unchanged_cache(self):
        def get_page(session, url):
            return self.index if url == INDEX_URL else page(introduction='New <b>official</b><br>text')
        with patch('campus_story_index.official_profiles.fetch_page', side_effect=get_page), \
             patch('campus_story_index.official_profiles.media_available', return_value=True):
            result = sync_profiles(self.root, self.cache)
            self.assertEqual(result['new']['introduction'], 'New official text')
            self.assertEqual(result['new']['quote'], ['A & B'])
            self.assertNotIn('waiting', result)
            before = self.cache.stat().st_mtime_ns
            self.assertEqual(sync_profiles(self.root, self.cache), result)
            self.assertEqual(self.cache.stat().st_mtime_ns, before)

    def test_both_voice_directories_are_tried_for_any_slug(self):
        with patch('campus_story_index.official_profiles.fetch_page', return_value=page()), \
             patch('campus_story_index.official_profiles.media_available',
                   side_effect=lambda session, url, kind: '/data/voice/' not in url) as available:
            result = fetch_profile(self.entry, {}, self.index)
        self.assertEqual(result['voices'], [ORIGIN + f'/assets/fresh/voice/voice_{i}.mp3' for i in (1, 2)])
        urls = [call.args[1] for call in available.call_args_list]
        self.assertIn(ORIGIN + '/assets/data/voice/fresh/voice_1.mp3', urls)
        with patch('campus_story_index.official_profiles.fetch_page', return_value=page()), \
             patch('campus_story_index.official_profiles.media_available', return_value=True) as available:
            fetch_profile(self.entry, result, self.index)
        self.assertNotIn(ORIGIN + '/assets/data/voice/fresh/voice_1.mp3', [call.args[1] for call in available.call_args_list])

    def test_media_failure_keeps_previous_urls_but_new_character_has_no_photo(self):
        old = {'photo': ORIGIN + '/assets/previous.png', 'voices': [ORIGIN + '/assets/data/voice/fresh/voice_1.mp3']}
        with patch('campus_story_index.official_profiles.fetch_page', return_value=page()), \
             patch('campus_story_index.official_profiles.media_available', return_value=False):
            result = fetch_profile(self.entry, old, self.index)
            self.assertEqual(result['photo'], old['photo'])
            self.assertEqual(result['voices'], old['voices'])
            empty = fetch_profile(self.entry, {}, self.index)
            self.assertIsNone(empty['photo'])
            self.assertEqual(empty['voices'], [])

    def test_network_and_markup_failures_preserve_previous_profile(self):
        previous = {'new': {'introduction': 'Cached text', 'photo': None, 'voices': [], 'quote': []}}
        self.cache.parent.mkdir()
        self.cache.write_text(json.dumps(previous))
        original = self.cache.read_bytes()
        for failure in (requests.ConnectionError('offline'), ValueError('changed markup')):
            with self.subTest(failure=type(failure).__name__), \
                 patch('campus_story_index.official_profiles.fetch_page', side_effect=failure):
                self.assertEqual(sync_profiles(self.root, self.cache), previous)
                self.assertEqual(self.cache.read_bytes(), original)
        with patch('campus_story_index.official_profiles.fetch_page', return_value=self.index), \
             patch('campus_story_index.official_profiles.fetch_profile', side_effect=requests.Timeout):
            self.assertEqual(sync_profiles(self.root, self.cache), previous)
            self.assertEqual(self.cache.read_bytes(), original)

    def test_first_run_offline_uses_packaged_profiles(self):
        seed = {'existing': {'introduction': 'Last known good'}}
        self.seed.write_text(json.dumps(seed))
        with patch('campus_story_index.official_profiles.fetch_page', side_effect=requests.Timeout):
            self.assertEqual(sync_profiles(self.root, self.cache), seed)
        self.assertEqual(json.loads(self.cache.read_text()), seed)

    def test_failed_character_does_not_discard_other_successful_updates(self):
        previous = {'new': {'introduction': 'Keep me'}}
        self.seed.write_text(json.dumps(previous))
        self.index.roster['FutureIdol'] = {**self.entry, 'url': '/idol/future/'}
        def refresh(entry, previous, index):
            if entry['url'] == '/idol/fresh/':
                raise requests.Timeout
            return {'introduction': 'Newly published', 'photo': None, 'voices': [], 'quote': []}
        with patch('campus_story_index.official_profiles.fetch_page', return_value=self.index), \
             patch('campus_story_index.official_profiles.fetch_profile', side_effect=refresh):
            result = sync_profiles(self.root, self.cache)
        self.assertEqual(result['new'], previous['new'])
        self.assertEqual(result['waiting']['introduction'], 'Newly published')

    def test_wrong_profile_or_external_link_is_not_accepted(self):
        with patch('campus_story_index.official_profiles.fetch_page', return_value=page(slug='saki')):
            with self.assertRaises(ValueError):
                fetch_profile(self.entry, {}, self.index)
        with patch('campus_story_index.official_profiles.requests.Session') as session:
            with self.assertRaises(ValueError):
                fetch_profile({**self.entry, 'url': 'https://example.com/idol/fresh/'}, {}, self.index)
            session.assert_not_called()

    def test_media_probe_checks_type_and_can_fall_back_from_head(self):
        session = MagicMock()
        response = session.head.return_value.__enter__.return_value
        response.status_code = 200
        response.headers = {'Content-Type': 'text/html'}
        self.assertFalse(media_available(session, ORIGIN + '/assets/image.png', 'image'))
        response.status_code = 405
        stream = session.get.return_value.__enter__.return_value
        stream.status_code = 206
        stream.headers = {'Content-Type': 'audio/mpeg'}
        self.assertTrue(media_available(session, ORIGIN + '/assets/voice.mp3', 'audio'))
        self.assertTrue(session.get.call_args.kwargs['stream'])
