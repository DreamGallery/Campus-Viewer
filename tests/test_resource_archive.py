import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from campus_story_index.runtime_update import publish
from campus_story_index.game_package import snapshot, stretch_size, classify, safe_name


def manifest(revision):
    return {'revision': revision, 'assetBundleList': [], 'resourceList': [
        {'name': 'adv_test.txt', 'md5': str(revision), 'size': 1}]}


class ArchiveTests(unittest.TestCase):
    def setup_files(self, root):
        for path in ['cache/web/catalog/manifest.json', 'cache/audio/clips/a.wav', 'repos/story/CSV/a.csv', 'repos/adv/Resource/a.txt']:
            file = root / path; file.parent.mkdir(parents=True, exist_ok=True); file.write_text('test')

    def test_baseline_dedup_and_retains_five_incremental_packages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.setup_files(root)
            def package(*args):
                dest = root / 'fake-output'; dest.mkdir(exist_ok=True)
                (dest / 'game.txt').write_text('decoded game output')
                return dest
            with patch('campus_story_index.resource_archive.build_package', side_effect=package) as build:
                publish(root, root / 'cache', root / 'repos', manifest(62))
                build.assert_not_called()
                self.assertEqual(json.loads((root/'current/resource-versions.json').read_text())['versions'], [])
                for revision in range(63, 69):
                    publish(root, root / 'cache', root / 'repos', manifest(revision))
                index=json.loads((root/'current/resource-versions.json').read_text())
                self.assertEqual([v['revision'] for v in index['versions']], ['68','67','66','65','64'])
                self.assertEqual(len(list((root/'downloads').glob('*.tar.gz'))),5)
                publish(root,root/'cache',root/'repos',manifest(68))
                self.assertEqual(build.call_count,6)
                with tarfile.open(root/'downloads'/index['versions'][0]['filename']) as archive:
                    self.assertEqual(archive.getnames(),['game.txt'])

    def test_failed_conversion_keeps_baseline_and_current(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.setup_files(root)
            first=publish(root,root/'cache',root/'repos',manifest(62))
            with patch('campus_story_index.resource_archive.build_package',side_effect=RuntimeError('failed')):
                with self.assertRaises(RuntimeError):publish(root,root/'cache',root/'repos',manifest(63))
            self.assertEqual((root/'current').resolve().name,first)
            self.assertEqual(json.loads((root/'current/resource-snapshot.json').read_text())['revision'],'62')

    def test_toolkit_dimensions_classification_and_safe_names(self):
        self.assertEqual(stretch_size('img_general_cidol-hski-3-001_0-full'),(1440,2560))
        self.assertEqual(stretch_size('img_general_csprt-3-001_full'),(2560,1440))
        self.assertEqual(stretch_size('img_adv_still_test'),(1440,2560))
        self.assertEqual(stretch_size('img_general_comic_test'),(1024,768))
        self.assertEqual(classify('resourceList','adv_test.txt'),'adventure')
        self.assertEqual(classify('assetBundleList','foo_shader_test'),'shader')
        with self.assertRaises(ValueError):safe_name('../evil')
        data=manifest(62);data['resourceList'][0]['state']=4
        self.assertEqual(snapshot(data),{})

    def test_incremental_download_skips_unchanged_and_tracks_removals(self):
        from types import SimpleNamespace
        from campus_story_index.game_package import build_package
        before=snapshot(manifest(62))
        current=manifest(63)
        unchanged={'name':'adv_keep.txt','size':1,'md5':'same'}
        before['resourceList/adv_keep.txt']=unchanged
        before['resourceList/adv_removed.txt']={'name':'adv_removed.txt','size':1,'md5':'gone'}
        current['resourceList'].append(unchanged)
        current['urlFormat']='https://example.invalid/{o}'
        def download(item,url,dest):
            dest.mkdir(parents=True,exist_ok=True);(dest/item['name']).write_text('x');return {'status':'downloaded'}
        def extract(kind,item,raw,dest):
            (dest/item['name']).write_text('decoded')
        with tempfile.TemporaryDirectory() as temp, patch.dict('sys.modules',{'UnityPy':SimpleNamespace(config=SimpleNamespace())}), patch('campus_story_index.game_package.download_one',side_effect=download) as fetch, patch('campus_story_index.game_package.extract_item',side_effect=extract):
            output=build_package(Path(temp),current,before)
            self.assertEqual(fetch.call_count,1)
            info=json.loads((output/'package.json').read_text())
            self.assertEqual(info['removed'],['resourceList/adv_removed.txt'])
            self.assertEqual(info['files'],1)
            self.assertEqual((output/'adv_test.txt').read_text(),'decoded')
