import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from campus_story_index.runtime_update import publish, update


class RuntimeUpdateTests(unittest.TestCase):
    def fixture(self, root):
        cache, repos = root / 'cache', root / 'repos'
        for path in ['web/catalog/manifest.json', 'audio/clips/bank/0001.wav']:
            p = cache / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('old')
        for path in ['story/CSV/a.csv', 'adv/Resource/a.txt']:
            p = repos / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('source')
        return cache, repos

    def test_publish_is_atomic_and_cache_replacements_do_not_modify_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); cache, repos = self.fixture(root)
            first = publish(root, cache, repos)
            p = cache / 'audio/clips/bank/0001.wav'; temp = p.with_suffix('.new'); temp.write_text('new'); os.replace(temp, p)
            self.assertEqual((root / 'current/audio/bank/0001.wav').read_text(), 'old')
            second = publish(root, cache, repos)
            self.assertNotEqual(first, second)
            self.assertEqual((root / 'current/audio/bank/0001.wav').read_text(), 'new')
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
