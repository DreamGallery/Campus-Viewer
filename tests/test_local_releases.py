import io
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from campus_story_index.local_releases import prune_local_releases, retention_count


class LocalReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.releases = self.root / 'releases'
        self.releases.mkdir()
        self.versions = []
        for number in range(4):
            release = self.releases / f'20261015T010000Z-{number:08x}'
            release.mkdir()
            (release / 'data').write_text(str(number))
            os.utime(release, ns=(number + 1, number + 1))
            self.versions.append(release)
        self.pointer = self.root / 'current'
        self.point_to(self.versions[-1])

    def point_to(self, target):
        self.pointer.unlink(missing_ok=True)
        self.pointer.symlink_to(target)

    def remaining(self):
        return [path for path in self.versions if path.exists()]

    def test_default_and_configurable_limit(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(retention_count(), 2)
        for value in ('0', '1', '5'):
            with patch.dict(os.environ, {'CAMPUS_LOCAL_RELEASES_KEEP': value}):
                self.assertEqual(retention_count(), int(value))
        for value in ('-1', '1.5', '', 'invalid'):
            with self.subTest(value=value), patch.dict(os.environ, {'CAMPUS_LOCAL_RELEASES_KEEP': value}):
                with self.assertRaises(ValueError):
                    retention_count()

    def test_keeps_current_and_newest_other_release(self):
        # Current can be older than a failed upload or a restored backup.
        self.point_to(self.versions[0])
        prune_local_releases(self.root, 2)
        self.assertEqual(self.remaining(), [self.versions[0], self.versions[3]])
        self.assertEqual((self.pointer / 'data').read_text(), '0')
        prune_local_releases(self.root, 2)
        self.assertEqual(len(self.remaining()), 2)

    def test_disabled_or_larger_limit_keeps_all_versions(self):
        for keep in (0, 10):
            prune_local_releases(self.root, keep)
            self.assertEqual(self.remaining(), self.versions)

    def test_current_only_preserves_cache_hardlinks_and_downloads(self):
        cache = self.root / 'cache/audio'
        cache.mkdir(parents=True)
        media = cache / 'clip.flac'
        media.write_bytes(b'audio')
        for release in self.versions:
            os.link(media, release / 'clip.flac')
        downloads = self.root / 'downloads'
        downloads.mkdir()
        archive = downloads / 'campus-resources-r70.tar.gz'
        archive.write_bytes(b'archive')
        prune_local_releases(self.root, 1)
        self.assertEqual(self.remaining(), [self.versions[-1]])
        self.assertEqual(media.read_bytes(), b'audio')
        self.assertEqual((self.pointer / 'clip.flac').read_bytes(), b'audio')
        self.assertEqual(media.stat().st_nlink, 2)
        self.assertEqual(archive.read_bytes(), b'archive')

    def test_ignores_staging_unmanaged_directories_and_symlinks(self):
        outside = self.root / 'unrelated'
        outside.mkdir()
        (outside / 'keep').write_text('safe')
        hidden = self.releases / '.20261015T020000Z-12345678'
        hidden.mkdir()
        unmanaged = self.releases / 'manual-backup'
        unmanaged.mkdir()
        linked = self.releases / '20261015T020000Z-12345678'
        linked.symlink_to(outside)
        (self.versions[0] / 'external-link').symlink_to(outside)
        prune_local_releases(self.root, 1)
        self.assertTrue(hidden.is_dir())
        self.assertTrue(unmanaged.is_dir())
        self.assertTrue(linked.is_symlink())
        self.assertEqual((outside / 'keep').read_text(), 'safe')

    def test_missing_broken_or_external_current_disables_cleanup(self):
        outside = self.root / self.versions[0].name
        outside.mkdir()
        for target in (None, self.releases / 'missing', outside):
            with self.subTest(target=target):
                self.pointer.unlink(missing_ok=True)
                if target is not None:
                    self.pointer.symlink_to(target)
                prune_local_releases(self.root, 1)
                self.assertEqual(self.remaining(), self.versions)

    def test_unmanaged_current_disables_cleanup(self):
        target = self.releases / 'manual-current'
        target.mkdir()
        self.point_to(target)
        prune_local_releases(self.root, 1)
        self.assertEqual(self.remaining(), self.versions)

    def test_symlinked_releases_directory_disables_cleanup(self):
        moved = self.root / 'elsewhere'
        self.releases.rename(moved)
        self.releases.symlink_to(moved)
        prune_local_releases(self.root, 1)
        self.assertEqual(self.remaining(), self.versions)

    def test_cleanup_errors_are_nonfatal_and_logged_without_details(self):
        output = io.StringIO()
        with patch('campus_story_index.local_releases.shutil.rmtree', side_effect=PermissionError('private path')), redirect_stdout(output):
            prune_local_releases(self.root, 1)
        self.assertEqual(self.remaining(), self.versions)
        self.assertIn('PermissionError', output.getvalue())
        self.assertNotIn('private path', output.getvalue())

    def test_pointer_change_stops_further_deletions(self):
        import shutil
        remove = shutil.rmtree
        def switch_after_delete(path):
            remove(path)
            self.point_to(self.versions[0])
        with patch('campus_story_index.local_releases.shutil.rmtree', side_effect=switch_after_delete) as cleanup:
            prune_local_releases(self.root, 1)
        self.assertEqual(cleanup.call_count, 1)
        self.assertEqual((self.pointer / 'data').read_text(), '0')
