import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_r2_publish import S3
from campus_story_index.music_publish import publish_music, prepare_library

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
