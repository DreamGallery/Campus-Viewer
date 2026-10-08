import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_r2_publish import S3
from campus_story_index.music_publish import publish_music, prepare_library
from campus_story_index.r2_publish import digest

class MusicPublishTests(unittest.TestCase):
    def library(self, root):
        (root/'song.flac').write_bytes(b'FLAC-sample')
        (root/'cover.png').write_bytes(b'cover')
        (root/'library.json').write_text(json.dumps({'schema_version':1,'revision':67,'tracks':[
            {'id':'song','format':'flac','audio':'/music/song.flac','cover':'/music/cover.png','lyrics':[]}]}))

    def test_immutable_assets_dedup_and_pointer_after_uploads(self):
        env={'CAMPUS_R2_ENDPOINT':'https://test','CAMPUS_R2_BUCKET':'b','CAMPUS_R2_PREFIX':'test',
             'AWS_ACCESS_KEY_ID':'test','AWS_SECRET_ACCESS_KEY':'test','CAMPUS_R2_PUBLIC_BASE_URL':'https://assets.test'}
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,env):
            root=Path(d);self.library(root);s3=S3()
            pointer=publish_music(root,s3)
            library=json.loads(s3.objects['test/'+pointer['library']])
            self.assertTrue(library['tracks'][0]['audio'].startswith('https://assets.test/test/media/'))
            before=s3.objects['test/music/current.json'];count=len(s3.uploads)
            publish_music(root,s3);self.assertEqual(len(s3.uploads),count)
            (root/'song.flac').write_bytes(b'changed');s3.fail='/song.flac'
            with self.assertRaises(RuntimeError):publish_music(root,s3)
            self.assertEqual(s3.objects['test/music/current.json'],before)
            self.assertEqual(json.loads((root/'library.json').read_text())['tracks'][0]['audio'],'/music/song.flac')

    def test_rejects_missing_files_and_mp3(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.library(root)
            (root/'song.flac').unlink()
            with self.assertRaises(ValueError):prepare_library(root,'test','')
            data=json.loads((root/'library.json').read_text());data['tracks'][0]['format']='mp3'
            (root/'library.json').write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'FLAC'):prepare_library(root,'test','')

    def test_reuses_release_inventory_and_rejects_size_collision(self):
        env = {'CAMPUS_R2_ENDPOINT':'https://test', 'CAMPUS_R2_BUCKET':'b', 'CAMPUS_R2_PREFIX':'test',
               'AWS_ACCESS_KEY_ID':'test', 'AWS_SECRET_ACCESS_KEY':'test'}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, env):
            root = Path(folder); self.library(root); s3 = S3()
            publish_music(root, s3)
            inventory = {key.removeprefix('test/'): len(value) for key, value in s3.objects.items()}
            s3.heads.clear(); s3.uploads.clear()
            publish_music(root, s3, inventory=inventory)
            self.assertEqual(s3.heads, [])
            self.assertEqual(s3.uploads, [])
            before = s3.objects['test/music/current.json']
            key = next(key for key in inventory if key.endswith('/song.flac'))
            inventory[key] += 1
            with self.assertRaisesRegex(ValueError, 'size mismatch'):
                publish_music(root, s3, inventory=inventory)
            self.assertEqual(s3.objects['test/music/current.json'], before)

    def test_shared_music_assets_are_hashed_once_per_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); self.library(root)
            path = root / 'library.json'; library = json.loads(path.read_text())
            library['tracks'].append({**library['tracks'][0], 'id': 'another'})
            path.write_text(json.dumps(library))
            with patch('campus_story_index.music_publish.digest', wraps=digest) as hashed:
                rewritten, jobs = prepare_library(root, 'test', '')
            self.assertEqual(hashed.call_count, 2)
            self.assertEqual(len(jobs), 2)
            self.assertEqual(rewritten['tracks'][0]['cover'], rewritten['tracks'][1]['cover'])
            self.assertEqual(json.loads(path.read_text()), library)
