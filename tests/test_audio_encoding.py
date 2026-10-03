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

    def test_cache_identity_includes_format_and_bitrate(self):
        from campus_story_index.voice_encoding import encoding_settings, audio_suffix
        for format in ('mp3', 'aac'):
            with self.subTest(format=format), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                settings = encoding_settings(format, 128)
                clip = root / ('clips/bank/0001' + audio_suffix(settings))
                clip.parent.mkdir(parents=True)
                clip.write_bytes(b'encoded')
                manifest = root / 'bank-manifests/bank.json'
                manifest.parent.mkdir()
                manifest.write_text(json.dumps({'source_md5': {'bank.acb': 'source'},
                    'decoder_sha256': 'decoder', 'voice_encoding': settings,
                    'clips': [{'path': str(clip.relative_to(root)), 'bytes': 7, 'sha256': file_digest(clip)}]}))
                args = ({'name': 'bank.acb', 'md5': 'source'}, None, root, 'unused', 'decoder')
                self.assertEqual(decode_bank(*args, settings=settings)['status'], 'cached')
                self.assertEqual(decode_bank(*args, settings=encoding_settings(format, 192))['error'], 'source_not_downloaded')
                self.assertEqual(decode_bank(*args)['error'], 'source_not_downloaded')
                clip.write_bytes(b'corrupt')
                self.assertEqual(decode_bank(*args, settings=settings)['error'], 'source_not_downloaded')

    def test_encoding_failure_keeps_existing_output(self):
        import subprocess
        import wave
        from campus_story_index.audio_extract import encode_audio
        from campus_story_index.voice_encoding import encoding_settings
        with tempfile.TemporaryDirectory() as folder:
            wav = Path(folder) / 'clip.wav'
            with wave.open(str(wav), 'wb') as file:
                file.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                file.writeframes(b'\0\0' * 4800)
            target = wav.with_suffix('.m4a')
            target.write_bytes(b'existing')
            def fail(args, **kwargs):
                target.with_name('.clip.m4a.tmp').write_bytes(b'partial')
                raise subprocess.CalledProcessError(1, args)
            with patch('campus_story_index.audio_extract.subprocess.run', side_effect=fail):
                with self.assertRaises(subprocess.CalledProcessError):
                    encode_audio(wav, encoding_settings('aac', 128))
            self.assertEqual(target.read_bytes(), b'existing')
            self.assertFalse(target.with_name('.clip.m4a.tmp').exists())
