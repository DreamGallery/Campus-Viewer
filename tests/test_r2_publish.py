import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from botocore.exceptions import ClientError
from campus_story_index.r2_publish import publish_release, UploadProgress, list_media

class S3:
    def __init__(self): self.objects={}; self.metadata={}; self.fail=None; self.uploads=[]; self.heads=[]; self.list_pages=0
    def get_object(self, Bucket, Key):
        if Key not in self.objects: raise ClientError({'Error':{'Code':'NoSuchKey'}}, 'GetObject')
        return {'Body':io.BytesIO(self.objects[Key]),'ETag':'etag'}
    def get_paginator(self, name):
        assert name == 'list_objects_v2'
        return self
    def paginate(self, Bucket, Prefix, PaginationConfig):
        assert PaginationConfig['PageSize'] == 1000
        items = [{'Key': k, 'Size': len(v)} for k, v in self.objects.items() if k.startswith(Prefix)]
        for start in range(0, max(1, len(items)), 1000):
            self.list_pages += 1
            yield {'Contents': items[start:start + 1000]}
    def head_object(self, Bucket, Key):
        self.heads.append(Key)
        if Key not in self.objects: raise ClientError({'Error':{'Code':'404'}}, 'HeadObject')
        return {'Metadata':self.metadata.get(Key,{})}
    def upload_file(self, filename, bucket, key, ExtraArgs, Callback):
        if self.fail and self.fail in key: raise RuntimeError('network failed')
        self.objects[key]=Path(filename).read_bytes();self.metadata[key]=ExtraArgs['Metadata'];self.uploads.append(key);Callback(len(self.objects[key]))
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
            mapping=json.loads(s3.objects['test/releases/first/file-map.json'])['files']
            data=json.loads(s3.objects['test/'+mapping['web/catalog/manifest.json']])
            self.assertEqual(data['base_path'],'/catalog/releases/first/builds/one')
            self.assertTrue(data['image'].startswith('https://assets.test/test/media/'))
            self.assertIn('/assets/images/',(root/'releases/first/web/catalog/manifest.json').read_text())
            (root/'current').symlink_to(root/'releases/first',target_is_directory=True)
            self.stage(root,'second');(root/'releases/second/adv/a.txt').write_text('changed');s3.fail='/a.txt';before=s3.objects['test/current.json']
            with self.assertRaises(RuntimeError):publish_release(root,'second',s3)
            self.assertEqual(before,s3.objects['test/current.json'])
            s3.fail=None;publish_release(root,'second',s3)
            self.assertEqual(json.loads(s3.objects['test/current.json'])['release'],'second')
            self.assertEqual(len([k for k in s3.uploads if '/media/' in k]),2)
            self.assertEqual(len([k for k in s3.heads if '/media/' in k]),2)
            self.assertEqual(len([k for k in s3.uploads if k.endswith('/a.csv')]),1)
            second_map=json.loads(s3.objects['test/releases/second/file-map.json'])['files']
            self.assertEqual(mapping['story/CSV/a.csv'],second_map['story/CSV/a.csv'])
            self.assertNotEqual(mapping['adv/a.txt'],second_map['adv/a.txt'])
    def test_legacy_csv_reused_without_reupload(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'CAMPUS_R2_ENDPOINT':'https://test', 'CAMPUS_R2_BUCKET':'b', 'CAMPUS_R2_PREFIX':'test', 'AWS_ACCESS_KEY_ID':'test', 'AWS_SECRET_ACCESS_KEY':'test'}):
            root=Path(d);s3=S3();self.stage(root,'old');self.stage(root,'new')
            (root/'current').symlink_to(root/'releases/old')
            s3.objects['test/current.json']=b'{"release":"old"}'
            s3.objects['test/releases/old/story/CSV/a.csv']=b'csv'
            s3.objects['test/releases/old/adv/a.txt']=b'txt'
            publish_release(root,'new',s3)
            mapping=json.loads(s3.objects['test/releases/new/file-map.json'])['files']
            self.assertEqual(mapping['story/CSV/a.csv'],'releases/old/story/CSV/a.csv')
            self.assertFalse(any(k.endswith('/a.csv') or k.endswith('/a.txt') for k in s3.uploads))

    def test_media_inventory_pagination_and_prefix_isolation(self):
        s3 = S3()
        s3.objects = {f'test/media/{i}/a.wav': b'abc' for i in range(2001)}
        s3.objects['foreign/media/a'] = b'foreign'
        s3.objects['test/releases/a'] = b'index'
        result = list_media(s3, 'b', 'test')
        self.assertEqual(len(result), 2001)
        self.assertEqual(s3.list_pages, 3)
        self.assertEqual(result['media/2000/a.wav'], 3)

    def test_size_mismatch_does_not_publish_or_overwrite(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'CAMPUS_R2_ENDPOINT':'https://test', 'CAMPUS_R2_BUCKET':'b', 'CAMPUS_R2_PREFIX':'test', 'AWS_ACCESS_KEY_ID':'test', 'AWS_SECRET_ACCESS_KEY':'test'}):
            root = Path(d); self.stage(root, 'first'); s3 = S3()
            key = 'test/media/' + hashlib.sha256(b'audio').hexdigest() + '/1.wav'
            s3.objects[key] = b'wrong-size'
            with self.assertRaisesRegex(RuntimeError, 'size mismatch'):
                publish_release(root, 'first', s3)
            self.assertNotIn('test/current.json', s3.objects)
            self.assertEqual(s3.objects[key], b'wrong-size')

    def test_missing_baseline_refuses_to_replace_existing_remote(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'CAMPUS_R2_ENDPOINT':'https://test','CAMPUS_R2_BUCKET':'b','CAMPUS_R2_PREFIX':'test','AWS_ACCESS_KEY_ID':'test','AWS_SECRET_ACCESS_KEY':'test'}):
            root=Path(d);self.stage(root,'new');s3=S3();s3.objects['test/current.json']=b'{"release":"old"}'
            with self.assertRaisesRegex(RuntimeError,'baseline'):publish_release(root,'new',s3)
            self.assertEqual(s3.uploads,[])

class ProgressTests(unittest.TestCase):
    def test_counts_bytes_skip_failure_and_final_output(self):
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            with UploadProgress('测试', 3) as progress:
                progress.transferred(1048576)
                progress.finish('uploaded')
                progress.finish('skipped')
                progress.finish('failed')
        self.assertIn('3/3 (100.0%)', output.getvalue())
        self.assertIn('已上传=1 已跳过=1 失败=1', output.getvalue())
        self.assertIn('本轮传输=1.0 MiB', output.getvalue())
        self.assertFalse(progress.thread.is_alive())
