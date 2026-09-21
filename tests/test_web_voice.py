import json
import tempfile
import unittest
from pathlib import Path
from campus_story_index.web_voice import chapter_voices

class WebVoiceTest(unittest.TestCase):
    def test_only_verified_explicit_links_and_safe_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = {'sources': {'csv_sha256': 'abc'}, 'voice_events': [{'id': 'v1', 'audio_variants': [
                {'status': 'verified', 'audio_path': 'clips/bank/0001.wav', 'voice_ref': 'v1'},
                {'status': 'unverified', 'audio_path': 'clips/bank/0002.wav'},
                {'status': 'verified', 'audio_path': 'clips/../bad.wav'}]}], 'lines': [
                {'csv_match_status': 'matched', 'audio_status': 'linked', 'voice_event_ids': ['v1'], 'csv_record_index': 1, 'text': 'hi', 'speaker': 'A'},
                {'csv_match_status': 'matched', 'audio_status': 'context_audio_only', 'voice_event_ids': ['v1']}]}
            (root/'sample.json').write_text(json.dumps(data))
            result = chapter_voices(root, {'path':'sample.json'})
            self.assertEqual(result['source_sha256'], 'abc')
            self.assertEqual(len(result['lines']), 1)
            self.assertEqual(result['lines'][0]['clips'], [{'url':'/audio/bank/0001.wav', 'label':'v1'}])
    def test_missing_index_is_empty(self):
        self.assertEqual(chapter_voices(Path('.'), None)['lines'], [])
