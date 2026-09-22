import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from botocore.exceptions import ClientError
from campus_story_index.r2_publish import publish_release

class S3:
    def __init__(self): self.objects={}; self.metadata={}; self.fail=None; self.uploads=[]
    def get_object(self, Bucket, Key):
        if Key not in self.objects: raise ClientError({'Error':{'Code':'NoSuchKey'}}, 'GetObject')
        return {'Body':io.BytesIO(self.objects[Key]),'ETag':'etag'}
    def head_object(self, Bucket, Key):
        if Key not in self.objects: raise ClientError({'Error':{'Code':'404'}}, 'HeadObject')
        return {'Metadata':self.metadata.get(Key,{})}
    def upload_file(self, filename, bucket, key, ExtraArgs):
        if self.fail and self.fail in key: raise RuntimeError('network failed')
        self.objects[key]=Path(filename).read_bytes();self.metadata[key]=ExtraArgs['Metadata'];self.uploads.append(key)
    def put_object(self, Bucket, Key, Body, **kwargs):
        if kwargs.get('IfNoneMatch') == '*' and Key in self.objects: raise RuntimeError('conflict')
        self.objects[Key]=Body
    def delete_object(self, Bucket, Key): self.objects.pop(Key,None)

class R2Tests(unittest.TestCase):
    def stage(self,root,name):
        stage=root/'releases'/name
        files={'web/catalog/manifest.json':json.dumps({'base_path':'/catalog/builds/one','image':'/assets/images/a.png'}),
               'web/catalog/builds/one/chapters/a.json':json.dumps({'url':'/audio/b/1.wav'}),
               'web/assets/images/a.png':'image','audio/b/1.wav':'audio','story/CSV/a.csv':'csv','adv/a.txt':'txt',
               'resource-versions.json':json.dumps({'revision':62,'versions':[]}), 'resource-snapshot.json':'{}'}
        for name,value in files.items():
            path=stage/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value)
    def test_atomic_failure_dedupe_and_original_release_unchanged(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'CAMPUS_R2_ENDPOINT':'https://test','CAMPUS_R2_BUCKET':'b','CAMPUS_R2_PREFIX':'test','AWS_ACCESS_KEY_ID':'test','AWS_SECRET_ACCESS_KEY':'test','CAMPUS_R2_PUBLIC_BASE_URL':'https://assets.test'}):
            root=Path(d);s3=S3();self.stage(root,'first')
            publish_release(root,'first',s3)
            data=json.loads(s3.objects['test/releases/first/web/catalog/manifest.json'])
            self.assertEqual(data['base_path'],'/catalog/releases/first/builds/one')
            self.assertTrue(data['image'].startswith('https://assets.test/test/media/'))
            self.assertIn('/assets/images/',(root/'releases/first/web/catalog/manifest.json').read_text())
            (root/'current').symlink_to(root/'releases/first',target_is_directory=True)
            self.stage(root,'second');s3.fail='second/adv';before=s3.objects['test/current.json']
            with self.assertRaises(RuntimeError):publish_release(root,'second',s3)
            self.assertEqual(before,s3.objects['test/current.json'])
            s3.fail=None;publish_release(root,'second',s3)
            self.assertEqual(json.loads(s3.objects['test/current.json'])['release'],'second')
            self.assertEqual(len([k for k in s3.uploads if '/media/' in k]),2)
    def test_missing_baseline_refuses_to_replace_existing_remote(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'CAMPUS_R2_ENDPOINT':'https://test','CAMPUS_R2_BUCKET':'b','CAMPUS_R2_PREFIX':'test','AWS_ACCESS_KEY_ID':'test','AWS_SECRET_ACCESS_KEY':'test'}):
            root=Path(d);self.stage(root,'new');s3=S3();s3.objects['test/current.json']=b'{"release":"old"}'
            with self.assertRaisesRegex(RuntimeError,'baseline'):publish_release(root,'new',s3)
            self.assertEqual(s3.uploads,[])
