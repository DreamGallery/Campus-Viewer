import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from campus_story_index.voice_encoding import encoding_settings, initialize_voice_encoding


class VoiceSettingsTests(unittest.TestCase):
    def test_formats_and_bitrates(self):
        self.assertEqual(encoding_settings(), {'format': 'flac', 'compression_level': 8})
        self.assertEqual(encoding_settings('MP3', '192k'), {'format': 'mp3', 'bitrate_kbps': 192})
        self.assertEqual(encoding_settings('aac')['bitrate_kbps'], 128)
        for format, bitrate in [('ogg', None), ('mp3', 99), ('aac', 0), ('aac', 321), ('aac', 'abc'), ('flac', 128)]:
            with self.subTest(format=format, bitrate=bitrate), self.assertRaises(ValueError):
                encoding_settings(format, bitrate)

    def test_first_run_persists_and_restart_without_environment_reuses(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.dict(os.environ, {'CAMPUS_VOICE_FORMAT':'aac', 'CAMPUS_VOICE_BITRATE':'96k'}, clear=True):
                selected = initialize_voice_encoding(root)
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(initialize_voice_encoding(root), selected)
            with patch.dict(os.environ, {'CAMPUS_VOICE_BITRATE':'192'}, clear=True):
                with self.assertRaises(ValueError): initialize_voice_encoding(root)
            self.assertEqual(json.loads((root/'voice-encoding.json').read_text()), selected)

    def test_existing_flac_installation_cannot_silently_change_format(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root/'cache/audio/bank-manifests/old.json'
            path.parent.mkdir(parents=True); path.write_text('{}')
            with patch.dict(os.environ, {'CAMPUS_VOICE_FORMAT':'mp3'}, clear=True):
                with self.assertRaises(ValueError): initialize_voice_encoding(root)
            self.assertFalse((root/'voice-encoding.json').exists())
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(initialize_voice_encoding(root), encoding_settings())

    def test_invalid_initial_config_does_not_persist(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'CAMPUS_VOICE_FORMAT':'mp3', 'CAMPUS_VOICE_BITRATE':'99'}, clear=True):
            with self.assertRaises(ValueError): initialize_voice_encoding(folder)
            self.assertFalse((Path(folder)/'voice-encoding.json').exists())
