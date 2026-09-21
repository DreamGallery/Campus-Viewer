import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from campus_story_index.adv import parse_command, parse_script
from campus_story_index.audio_download import bank_for_cue, download_one, valid_download, make_plan
from campus_story_index.audio_extract import decode_bank
from campus_story_index.voice_index import align_csv, audio_variants, make_script, match_voice, speaker_resolver


def command(tag, attrs='', start=0, duration=2):
    clip = json.dumps({'_startTime': start, '_duration': duration, '_clipIn': 0.0}, separators=(',', ':'))
    clip = clip.replace('{', r'\{').replace('}', r'\}')
    return f'[{tag} {attrs} clip={clip}]'


def csv_bytes(rows):
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer)
    writer.writerow(['id', 'name', 'text', 'trans'])
    writer.writerows(rows)
    return buffer.getvalue().encode()


def characters():
    return [{'id': cid, 'name': name, 'speaker_names': [name], 'speaker_patterns': [name + '$'],
             'source_record_ids': ['Character:' + cid]} for cid, name in [('amao', '麻央'), ('hski', '咲季')]]


class AdvAndVoiceTest(unittest.TestCase):
    def test_parser_preserves_text_escapes_and_nested_choices(self):
        text = r'[choicegroup choices=[choice text=一行\n二行] choices=[choice text=<r\=x>字</r>]]'
        result = parse_command(text)
        self.assertEqual(result['choices'][1]['text'], r'<r\=x>字</r>')
        self.assertEqual(len(result['choices']), 2)

    def test_malformed_input_fails(self):
        with self.assertRaises(ValueError):
            parse_command('[message text=unclosed')

    def test_nested_branch_lengths_count_children_not_flat_lines(self):
        text = '\n'.join(['[branchgroup type=Choice groupLength=2]', '[branch groupLength=1]',
                          '[branchgroup type=Choice groupLength=1]', '[branch groupLength=1]',
                          command('message', 'text=A name=麻央'), '[branch groupLength=1]',
                          command('message', 'text=B name=麻央'), command('message', 'text=C name=麻央')])
        rows = parse_script(text, 'adv_test')['texts']
        self.assertIn('group:1/branch:0/group:1/branch:0', rows[0]['scope'])
        self.assertEqual(rows[1]['scope'], 'group:1/branch:1/timeline:0')
        self.assertEqual(rows[2]['scope'], 'timeline:0')

    def test_legacy_inline_choice_child(self):
        text = '\n'.join(['[branchgroup groupLength=2]', '[choicegroup choices=[choice text=選ぶ]]',
                          '[branch]', command('message', 'text=続き name=麻央')])
        self.assertEqual([r['kind'] for r in parse_script(text, 'adv_test')['texts']], ['choice', 'message'])

    def test_no_cross_branch_voice_matching(self):
        text = '\n'.join(['[branchgroup groupLength=2]', '[branch groupLength=1]',
                          command('message', 'text=A name=麻央'), '[branch groupLength=1]',
                          command('voice', 'voice=sud_vo_adv_test_amao-001 actorId=amao', 0.1)])
        parsed = parse_script(text, 'adv_test')
        match = match_voice(parsed['voices'][0], parsed['texts'], speaker_resolver(characters()), {'amao', 'hski'})
        self.assertEqual(match['status'], 'no_text_in_scope')

    def test_exact_sequence_disambiguates_repeated_text(self):
        rows = [{'kind': 'dialogue', 'speaker': '麻央', 'text': 'はい'}] * 2
        source = [{'kind': 'message', 'speaker': '麻央', 'text': 'はい'}] * 2
        mapping, status, _ = align_csv(rows, source)
        self.assertEqual(mapping, {0: 0, 1: 1})
        self.assertEqual(status, 'exact_sequence')

    def test_changed_sequence_does_not_guess_duplicate_occurrences(self):
        rows = [{'kind': 'dialogue', 'speaker': '麻央', 'text': 'はい'}]
        source = [{'kind': 'message', 'speaker': '麻央', 'text': 'はい'}] * 2
        mapping, status, candidates = align_csv(rows, source)
        self.assertEqual(mapping, {})
        self.assertEqual(candidates, {0: [0, 1]})

    def test_missing_narrator_name_normalized(self):
        mapping, status, _ = align_csv([{'kind': 'dialogue', 'speaker': '', 'text': '説明'}],
                                       [{'kind': 'message', 'speaker': '__narration__', 'text': '説明'}])
        self.assertEqual(status, 'normalized_narrator_sequence')
        self.assertEqual(mapping, {0: 0})

    def test_cue_identity_precedes_animation_actor(self):
        text = '\n'.join([command('message', 'text=A name=麻央'),
                          command('voice', 'voice=sud_vo_adv_test_amao-001 actorId=hski', 0.1)])
        parsed = parse_script(text, 'adv_test')
        match = match_voice(parsed['voices'][0], parsed['texts'], speaker_resolver(characters()), {'amao', 'hski'})
        self.assertEqual(match['status'], 'matched_temporally')
        self.assertEqual(match['speaker_evidence'], 'consistent')

    def test_other_speaker_is_context_not_spoken_line(self):
        text = '\n'.join([command('message', 'text=A name=麻央'),
                          command('voice', 'voice=sud_vo_adv_test_hski-001 actorId=hski', 0.1)])
        parsed = parse_script(text, 'adv_test')
        match = match_voice(parsed['voices'][0], parsed['texts'], speaker_resolver(characters()), {'amao', 'hski'})
        self.assertEqual(match['status'], 'speaker_conflict')
        self.assertEqual(match['text_ids'], [])
        self.assertEqual(match['context_text_ids'], [parsed['texts'][0]['id']])

    def test_ambiguous_time_window_not_forced(self):
        text = '\n'.join([command('message', 'text=A name=麻央'), command('message', 'text=B name=麻央'),
                          command('voice', 'voice=sud_vo_adv_test_amao-001', 0.1)])
        parsed = parse_script(text, 'adv_test')
        match = match_voice(parsed['voices'][0], parsed['texts'], speaker_resolver(characters()), {'amao'})
        self.assertEqual(match['status'], 'ambiguous')

    def test_dynamic_bindings_keep_contexts(self):
        entries = [{'id': 'a', 'character_ids': ['amao'], 'voice_bindings': [{'source_field': 'voiceAssetId', 'asset_id': 'sud_a'}]},
                   {'id': 'b', 'character_ids': ['hski'], 'voice_bindings': [{'source_field': 'voiceAssetId', 'asset_id': 'sud_b'}]}]
        clips = {('sud_a', 'sud_a'): [{'id': 'clip_a', 'path': 'clips/a.wav', 'duration_ms': 1000}]}
        result = audio_variants({'voice_ref': '{voice_asset_id}'}, entries, {'sud_a': 'sud_a', 'sud_b': 'sud_b'}, clips)
        self.assertEqual(result[0]['status'], 'verified')
        self.assertEqual(result[0]['entry_ids'], ['a'])
        self.assertEqual(result[1]['status'], 'cue_not_found')

    def test_missing_cue_never_falls_back_to_first_bank_stream(self):
        clips = {('bank', 'different'): [{'id': 'wrong', 'path': 'wrong.wav', 'duration_ms': 1000}]}
        result = audio_variants({'voice_ref': 'sud_missing'}, [], {'sud_missing': 'bank'}, clips)
        self.assertEqual(result[0]['status'], 'cue_not_found')
        self.assertIsNone(result[0]['audio_path'])

    def test_translation_change_preserves_line_identity(self):
        adv = command('message', 'text=A name=麻央').encode()
        def make(translation):
            return make_script('adv_test', csv_bytes([['0', '麻央', 'A', translation]]), adv,
                               [], {'amao'}, {}, {}, speaker_resolver(characters()))
        first, second = make(''), make('译文')
        self.assertEqual(first['lines'][0]['id'], second['lines'][0]['id'])
        self.assertEqual(second['lines'][0]['translation'], '译文')
        self.assertEqual(second['lines'][0]['audio_status'], 'no_explicit_voice')

    def test_voice_index_schema(self):
        from jsonschema import Draft202012Validator
        adv = command('message', 'text=A name=麻央').encode()
        result = make_script('adv_test', csv_bytes([['0', '麻央', 'A', '']]), adv,
                             [], {'amao'}, {}, {}, speaker_resolver(characters()))
        result['sources'] = {'csv_path': 'CSV/adv_test.csv', 'csv_sha256': 'hash',
                             'adv_path': 'adv_test.txt', 'adv_sha256': 'hash'}
        schema = json.loads((Path(__file__).resolve().parents[1] / 'docs/voice-index.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(result)

    def test_choice_never_gets_neighbor_voice(self):
        adv = '\n'.join([command('choicegroup', 'choices=[choice text=A]'),
                         command('voice', 'voice=sud_vo_adv_test_amao-001', 0.1)]).encode()
        result = make_script('adv_test', csv_bytes([['select', '', 'A', '']]), adv,
                             [], {'amao'}, {}, {}, speaker_resolver(characters()))
        self.assertEqual(result['lines'][0]['audio_status'], 'choice')
        self.assertEqual(result['lines'][0]['voice_event_ids'], [])


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.content = b'test audio bytes'
        self.item = {'name': 'test.acb', 'size': len(self.content),
                     'md5': hashlib.md5(self.content).hexdigest(), 'objectName': 'object'}

    def test_plan_handles_reordered_voice_attributes(self):
        (self.root / 'adv_test.txt').write_text('[voice actorId=amao voice=sud_vo_adv_test_amao-001]')
        manifest = {'revision': 1, 'resourceList': [dict(self.item, name='sud_vo_adv_test.acb')]}
        plan = make_plan(manifest, self.root, {'entries': []})
        self.assertEqual(plan['cue_banks'], {'sud_vo_adv_test_amao-001': 'sud_vo_adv_test'})

    def test_longest_prefix_candidate(self):
        self.assertEqual(bank_for_cue('sud_vo_adv_x_y_001', {'sud_vo_adv_x', 'sud_vo_adv_x_y'}), 'sud_vo_adv_x_y')

    def test_existing_download_checked_by_md5_and_size(self):
        file = self.root / 'test.acb'
        file.write_bytes(self.content)
        with patch('campus_story_index.audio_download.requests.get', side_effect=AssertionError('should not request')):
            self.assertEqual(download_one(self.item, 'https://example/{o}', self.root)['status'], 'cached')
        file.write_bytes(b'x' * len(self.content))
        self.assertFalse(valid_download(file, self.item))

    def test_bad_download_does_not_delete_previous_source(self):
        file = self.root / 'test.acb'
        file.write_bytes(b'original')
        with patch('campus_story_index.audio_download.requests.get') as mock:
            mock.return_value.__enter__.return_value.status_code = 200
            mock.return_value.__enter__.return_value.iter_content.return_value = [b'bad']
            result = download_one(self.item, 'https://example/{o}', self.root, retries=1)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(file.read_bytes(), b'original')
        self.assertEqual(list(self.root.glob('.test.acb*')), [])

    def test_decoder_failure_preserves_source(self):
        banks = self.root / 'banks'
        banks.mkdir()
        (banks / 'test.acb').write_bytes(self.content)
        with patch('campus_story_index.audio_extract.subprocess.run') as mock:
            mock.return_value.returncode = 1
            result = decode_bank(self.item, None, self.root, '/decoder', 'hash')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual((banks / 'test.acb').read_bytes(), self.content)
        self.assertFalse((self.root / 'bank-manifests/test.json').exists())


if __name__ == '__main__':
    unittest.main()
