import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from campus_story_index.audio_extract import decode_bank, file_digest

class AudioEncodingTests(unittest.TestCase):
    def test_reuses_verified_flac_cache_without_conversion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            clip = root / 'clips/bank/0001.flac'
            clip.parent.mkdir(parents=True)
            clip.write_bytes(b'fLaC')
            manifest = root / 'bank-manifests/bank.json'
            manifest.parent.mkdir()
            data = {'source_md5': {'bank.acb':'source'}, 'decoder_sha256':'decoder',
                'clips':[{'path':'clips/bank/0001.flac', 'bytes':4, 'sha256':file_digest(clip)}]}
            manifest.write_text(json.dumps(data))
            with patch('campus_story_index.audio_extract.encode_flac') as encoder:
                result = decode_bank({'name':'bank.acb','md5':'source'},None,root,'unused','decoder')
                self.assertEqual(result['status'],'cached')
                encoder.assert_not_called()
            # Legacy WAV metadata cannot be mistaken for a ready FLAC cache.
            wav = clip.with_suffix('.wav')
            wav.write_bytes(b'pcm')
            data['clips'] = [{'path':'clips/bank/0001.wav','bytes':3,'sha256':file_digest(wav)}]
            manifest.write_text(json.dumps(data))
            result = decode_bank({'name':'bank.acb','md5':'source'},None,root,'unused','decoder')
            self.assertEqual(result['error'],'source_not_downloaded')
            self.assertTrue(wav.exists())
