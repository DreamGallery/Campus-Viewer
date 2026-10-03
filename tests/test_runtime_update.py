import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from campus_story_index.runtime_update import publish, update, input_signature


class RuntimeUpdateTests(unittest.TestCase):
    def fixture(self, root):
        cache, repos = root / 'cache', root / 'repos'
        for path in ['web/catalog/manifest.json', 'audio/clips/bank/0001.flac']:
            p = cache / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('old')
        for path in ['story/CSV/a.csv', 'adv/Resource/a.txt']:
            p = repos / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('source')
        return cache, repos

    def test_publish_is_atomic_and_cache_replacements_do_not_modify_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); cache, repos = self.fixture(root)
            first = publish(root, cache, repos)
            p = cache / 'audio/clips/bank/0001.flac'; temp = p.with_suffix('.new'); temp.write_text('new'); os.replace(temp, p)
            self.assertEqual((root / 'current/audio/bank/0001.flac').read_text(), 'old')
            second = publish(root, cache, repos)
            self.assertNotEqual(first, second)
            self.assertEqual((root / 'current/audio/bank/0001.flac').read_text(), 'new')
            self.assertTrue((root / 'releases' / first).exists())

    def test_failed_publish_preserves_current_release(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); cache, repos = self.fixture(root); first = publish(root, cache, repos)
            with patch('campus_story_index.runtime_update.shutil.copytree', side_effect=OSError('disk full')):
                with self.assertRaises(OSError): publish(root, cache, repos)
            self.assertEqual((root / 'current').resolve().name, first)

    def test_first_failure_records_safe_status_without_publishing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch('campus_story_index.runtime_update.sync_repo', side_effect=RuntimeError('secret')):
                self.assertFalse(update(root))
            status = json.loads((root / 'status.json').read_text())
            self.assertEqual(status['state'], 'error'); self.assertNotIn('secret', status['error'])
            self.assertFalse((root / 'current').exists())

    def test_lock_does_not_start_second_update(self):
        import fcntl
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with (root / 'update.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch('campus_story_index.runtime_update.sync_repo') as sync:
                    self.assertFalse(update(root)); sync.assert_not_called()

    def test_unchanged_inputs_skip_build_and_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); saved=root/'releases/old'; saved.mkdir(parents=True)
            (saved/'update-inputs.json').write_text('{"signature":"same"}')
            (root/'current').symlink_to(saved)
            with patch('campus_story_index.runtime_update.fetch_masterdata',return_value=(Path('/fake-master'),{'version':'test'})), patch('campus_story_index.runtime_update.sync_repo'), patch('campus_story_index.runtime_update.fetch_manifest',return_value={'revision':62}), patch('campus_story_index.runtime_update.input_signature',return_value='same'), patch('campus_story_index.runtime_update.command') as command, patch('campus_story_index.runtime_update.publish') as pub:
                self.assertTrue(update(root));command.assert_not_called();pub.assert_not_called()
            self.assertEqual(json.loads((root/'status.json').read_text())['state'],'ready')

    def test_commit_or_manifest_change_changes_signature(self):
        with patch('campus_story_index.runtime_update.subprocess.check_output',return_value=b'commit-a'):
            first=input_signature(Path('/fake'),{'revision':62})
            self.assertNotEqual(first,input_signature(Path('/fake'),{'revision':63}))
        with patch('campus_story_index.runtime_update.subprocess.check_output',return_value=b'commit-b'):
            self.assertNotEqual(first,input_signature(Path('/fake'),{'revision':62}))


class MasterSourceTests(unittest.TestCase):
    def test_api_snapshot_changes_signature_without_master_git_checkout(self):
        with patch('campus_story_index.runtime_update.subprocess.check_output', return_value=b'commit') as git:
            one = input_signature(Path('/fake'), {}, {'version': 'one'})
            two = input_signature(Path('/fake'), {}, {'version': 'two'})
            self.assertNotEqual(one, two)
            self.assertTrue(all('/fake/master' not in call.args[0] for call in git.call_args_list))

    def test_fetch_masterdata_pins_current_snapshot(self):
        from campus_story_index.runtime_update import fetch_masterdata
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            snapshot = root / 'cache/masterdb/versions/one'
            snapshot.mkdir(parents=True)
            (snapshot / 'snapshot.json').write_text('{"version":"one"}')
            (root / 'cache/masterdb/current').symlink_to(snapshot)
            with patch.dict(os.environ, {'CAMPUS_MASTER_SOURCE':'api'}), patch('campus_story_index.runtime_update.command') as command:
                path, state = fetch_masterdata(root, root/'repos')
            self.assertEqual(path, snapshot)
            self.assertEqual(state['version'], 'one')
            self.assertIn('hatsuboshi_master', command.call_args.args[0])

    def test_failed_master_fetch_cannot_fall_back_to_old_git_tables(self):
        from campus_story_index.runtime_update import fetch_masterdata
        with patch.dict(os.environ, {'CAMPUS_MASTER_SOURCE':'api'}), patch('campus_story_index.runtime_update.command', side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError): fetch_masterdata(Path('/fake'), Path('/fake/repos'))


class VoiceRuntimeTests(unittest.TestCase):
    def test_api_masterdb_and_selected_voice_encoding_are_used_together(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                'CAMPUS_MASTER_SOURCE': 'api', 'CAMPUS_VOICE_FORMAT': 'aac',
                'CAMPUS_VOICE_BITRATE': '96'}, clear=True):
            root = Path(folder)
            master = root / 'master-snapshot'
            with patch('campus_story_index.runtime_update.sync_repo') as sync, \
                 patch('campus_story_index.runtime_update.fetch_masterdata', return_value=(master, {'version': 'one'})), \
                 patch('campus_story_index.runtime_update.fetch_manifest', return_value={'revision': 67}), \
                 patch('campus_story_index.runtime_update.input_signature', return_value='new'), \
                 patch('campus_story_index.runtime_update.command') as command, \
                 patch('campus_story_index.runtime_update.publish', return_value='new'):
                self.assertTrue(update(root))
                self.assertNotIn('master', [call.args[1] for call in sync.call_args_list])
                calls = [call.args[0] for call in command.call_args_list]
                extract = next(args for args in calls if 'campus_story_index.audio_extract' in args)
                self.assertEqual(extract[extract.index('--format') + 1], 'aac')
                self.assertEqual(extract[extract.index('--bitrate') + 1], '96')
                catalog = next(args for args in calls if 'campus_story_index' in args)
                self.assertEqual(catalog[catalog.index('--masterdata') + 1], master)
